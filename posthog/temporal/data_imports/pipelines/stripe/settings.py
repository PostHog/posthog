"""Stripe analytics source settings and constants"""

# the most popular endpoints
# Full list of the Stripe API endpoints you can find here: https://stripe.com/docs/api.
# These endpoints are converted into ExternalDataSchema objects when a source is linked.
ENDPOINTS = ("BalanceTransaction", "Subscription", "Customer", "Product", "Price", "Invoice", "Charge")

DEFAULT_ENDPOINTS = ("BalanceTransaction", "Subscription", "Customer", "Product", "Price", "Invoice", "Charge")

ALL_ENDPOINTS = (
    "Account",
    "ApplicationFee",
    "BalanceTransaction",
    "Charge",
    "CountrySpec",
    "Coupon",
    "CreditNote",
    "CreditNoteLineItem",
    "Customer",
    "CustomerBalanceTransaction",
    "Dispute",
    "Event",
    "ExchangeRate",
    "File",
    "FileLink",
    "FileUpload",
    "Invoice",
    "InvoiceItem",
    "PaymentIntent",
    "PaymentLink",
    "PaymentMethod",
    "PaymentMethodConfiguration",
    "PaymentMethodDomain",
    "Payout",
    "Plan",
    "Price",
    "Product",
    "PromotionCode",
    "Quote",
    "Refund",
    "Review",
    "SetupAttempt",
    "SetupIntent",
    "ShippingRate",
    "Subscription",
    "SubscriptionItem",
    "SubscriptionSchedule",
    "TaxCode",
    "TaxRate",
    "Topup",
    "Transfer",
)
