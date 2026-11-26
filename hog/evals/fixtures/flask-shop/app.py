import uuid

from flask import Flask, abort, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "dev-only-secret"

PRODUCTS = {
    "trail-mug": {"name": "Trail mug", "price": 18},
    "canvas-tote": {"name": "Canvas tote", "price": 24},
    "wool-beanie": {"name": "Wool beanie", "price": 32},
}

USERS: dict[str, dict] = {}


@app.get("/")
def index():
    return render_template("index.html", products=PRODUCTS)


@app.get("/products/<slug>")
def product(slug: str):
    item = PRODUCTS.get(slug) or abort(404)
    return render_template("product.html", slug=slug, product=item)


@app.post("/products/<slug>/cart")
def add_to_cart(slug: str):
    if slug not in PRODUCTS:
        abort(404)
    session.setdefault("cart", []).append(slug)
    session.modified = True
    return redirect(url_for("product", slug=slug, added=1))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")
    email = request.form.get("email", "")
    if "@" not in email:
        return render_template("signup.html", error="Enter a valid email."), 400
    user = {"id": str(uuid.uuid4()), "email": email}
    USERS[user["id"]] = user
    session["user_id"] = user["id"]
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))
