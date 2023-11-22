"""Stripe analytics source settings and constants"""

# the most popular endpoints
# Full list of the Stripe API endpoints you can find here: https://stripe.com/docs/api.
ENDPOINTS = (
    "Subscription",
    "Account",
    "Coupon",
    "Customer",
    "Product",
    "Price",
)
# possible incremental endpoints
INCREMENTAL_ENDPOINTS = ("Event", "Invoice", "BalanceTransaction")
