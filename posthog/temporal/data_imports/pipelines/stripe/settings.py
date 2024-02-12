"""Stripe analytics source settings and constants"""

# the most popular endpoints
# Full list of the Stripe API endpoints you can find here: https://stripe.com/docs/api.
# These endpoints are converted into ExternalDataSchema objects when a source is linked.
ENDPOINTS = ("BalanceTransaction", "Subscription", "Customer", "Product", "Price", "Invoice", "Charge")
