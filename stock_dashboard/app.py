from flask import Flask, render_template, request, jsonify
import yfinance as yf
import sqlite3
import datetime
import os

app = Flask(__name__)

# ---------- DATABASE SETUP ----------
DB_NAME = 'stocks.db'

def init_db():
    if not os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                action TEXT,
                quantity INTEGER,
                price REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

init_db()

# ---------- HELPERS ----------
def get_stock_price(symbol):
    try:
        stock = yf.Ticker(symbol)
        info = stock.info
        current_price = info.get('currentPrice')
        previous_close = info.get('previousClose')
        return current_price, previous_close, None
    except Exception as e:
        return None, None, str(e)

def record_transaction(symbol, action, quantity, price):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (symbol, action, quantity, price)
        VALUES (?, ?, ?, ?)
    ''', (symbol, action, quantity, price))
    conn.commit()
    conn.close()

def fetch_transactions():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, action, quantity, price, timestamp FROM transactions ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()

    transactions = []
    for row in rows:
        symbol = row[1]
        company_name = get_company_name(symbol)
        transactions.append({
            'id': row[0],
            'symbol': symbol,
            'action': row[2],
            'quantity': row[3],
            'price': row[4],
            'timestamp': row[5],
            'company_name': company_name
        })

    return transactions

def get_company_name(symbol):
    try:
        stock = yf.Ticker(symbol)
        return stock.info.get('longName', symbol)
    except Exception:
        return symbol

# ---------- ROUTES ----------
@app.route('/')
def index():
    top_symbols = ["AAPL", "TSLA", "GOOGL", "MSFT", "AMZN", "META"]
    stock_data = {}
    for symbol in top_symbols:
        price, prev, err = get_stock_price(symbol)
        stock_data[symbol] = {
            "price": price,
            "prev_close": prev,
            "error": err
        }
    return render_template('index.html', stocks=stock_data)

@app.route('/buy', methods=['GET', 'POST'])
def buy():
    if request.method == 'POST':
        symbol = request.form['symbol'].upper()
        quantity = int(request.form['quantity'])
        price, _, error = get_stock_price(symbol)

        if error:
            return render_template('buy.html', error=error)

        total = quantity * price
        record_transaction(symbol, 'BUY', quantity, price)
        return render_template('buy.html', success=True, symbol=symbol, quantity=quantity, total=total)

    return render_template('buy.html')

@app.route('/sell', methods=['GET', 'POST'])
def sell():
    success_message = None
    if request.method == 'POST':
        symbol = request.form['symbol'].upper()
        quantity = int(request.form['quantity'])
        price, _, error = get_stock_price(symbol)

        if error:
            return render_template('sell.html', error=error)

        total = quantity * price
        record_transaction(symbol, 'SELL', quantity, price)
        success_message = f"Successfully sold {quantity} shares of {symbol} at ${price:.2f} each, for a total of ${total:.2f}."

    top_symbols = ["AAPL", "TSLA", "GOOGL", "MSFT", "AMZN", "META"]
    stocks = []
    for symbol in top_symbols:
        price, _, err = get_stock_price(symbol)
        company_name = get_company_name(symbol)
        stocks.append({
            'symbol': symbol,
            'company_name': company_name,
            'price': price
        })

    return render_template('sell.html', stocks=stocks, success_message=success_message)

@app.route('/predict', methods=['GET', 'POST'])
def predict():
    import traceback
    from sklearn.linear_model import LinearRegression
    from sklearn.model_selection import train_test_split
    import pandas as pd

    try:
        if request.method == 'POST':
            # Handle both JSON and form requests
            if request.is_json:
                data = request.get_json()
                symbol = data.get('symbol', '').strip().upper()
                amount = int(data.get('amount', 1))
            else:
                symbol = request.form['symbol'].strip().upper()
                amount = 1

            print(f"[DEBUG] Symbol: {symbol}, Amount: {amount}")

            # Get historical data
            stock = yf.Ticker(symbol)
            stock_data = stock.history(period='1y')

            print("[DEBUG] Stock data empty:", stock_data.empty)

            if stock_data.empty:
                return jsonify({"error": "No historical data available for this symbol."}), 404

            # Prepare data
            stock_data = stock_data[['Close']]
            stock_data['Prediction'] = stock_data[['Close']].shift(-30)

            X = stock_data.drop(['Prediction'], axis=1).iloc[:-30]
            y = stock_data['Prediction'].iloc[:-30]

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
            model = LinearRegression()
            model.fit(X_train, y_train)

            # Predict next 30 days
            future = stock_data.drop(['Prediction'], axis=1).iloc[-30:]
            result = model.predict(future)
            predicted_price = round(result[-1], 2)

            # Get current & open prices
            info = stock.info
            print("[DEBUG] Stock info keys:", list(info.keys()))
            current_price = info.get('currentPrice')
            open_price = info.get('open')

            if current_price is None or open_price is None:
                return jsonify({"error": "Real-time data not available for this symbol."}), 500

            # Format response
            total_current = round(current_price * amount, 2)
            total_predicted = round(predicted_price * amount, 2)

            change_1_stock = f"{round(((current_price - open_price) / open_price) * 100, 2)}%"
            change_total = f"{round(((total_predicted - total_current) / total_current) * 100, 2)}%"

            return jsonify({
                "symbol": symbol,
                "open_price": round(open_price, 2),
                "current_price": round(current_price, 2),
                "total_current": total_current,
                "total_predicted": total_predicted,
                "change_1_stock": change_1_stock,
                "change_total": change_total
            })

        # GET request (from browser)
        return render_template('predict.html')

    except Exception as e:
        print("[ERROR] An unexpected error occurred during prediction:")
        traceback.print_exc()
        return jsonify({"error": "An unexpected error occurred during prediction."}), 500


@app.route('/holder')
def holder():
    transactions = fetch_transactions()
    return render_template('holder.html', transactions=transactions)

@app.route('/api/buy', methods=['POST'])
def api_buy():
    data = request.get_json()
    symbol = data.get('symbol', '').upper()
    quantity = int(data.get('quantity', 0))

    if not symbol or quantity <= 0:
        return jsonify({"success": False, "error": "Invalid symbol or quantity"}), 400

    price, _, error = get_stock_price(symbol)
    if error or price is None:
        return jsonify({"success": False, "error": error or "Failed to fetch stock price"}), 500

    total_cost = round(price * quantity, 2)
    record_transaction(symbol, 'BUY', quantity, price)

    return jsonify({"success": True, "total_cost": total_cost}), 200

@app.route('/api/sell', methods=['POST'])
def api_sell():
    data = request.get_json()
    symbol = data.get('symbol', '').upper()
    quantity = int(data.get('quantity', 0))

    if not symbol or quantity <= 0:
        return jsonify({"success": False, "error": "Invalid symbol or quantity"}), 400

    price, _, error = get_stock_price(symbol)
    if error or price is None:
        return jsonify({"success": False, "error": error or "Failed to fetch stock price"}), 500

    total_revenue = round(price * quantity, 2)
    record_transaction(symbol, 'SELL', quantity, price)

    return jsonify({"success": True, "total_revenue": total_revenue}), 200

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/signup')
def signup():
    return render_template('signup.html')

# ---------- RUN ----------
if __name__ == '__main__':
    app.run(debug=True)