from dataclasses import dataclass


@dataclass
class PaystackEndpointConfig:
    name: str
    # API path relative to https://api.paystack.co (e.g. "/transaction").
    path: str
    # Paystack list resources expose a globally-unique integer `id`, unique across the account.
    primary_key: str = "id"


# Paystack list endpoints. Each returns a `{"status", "message", "data": [...], "meta": {...}}`
# envelope and paginates by `page` / `perPage` (default 50, max 100). The schema name (dict key)
# is what `get_schemas` reports and what the synced warehouse table is named after.
#
# All endpoints are full-refresh today. Paystack list endpoints return rows newest-first
# (descending by creation time) and expose no documented stable ascending sort parameter, and the
# `from` / `to` creation-time filters could not be verified against the live API (no test
# credentials). Declaring incremental on unverified ordering risks watermark corruption, so
# incremental sync is intentionally deferred — see the note in `paystack.py`.
PAYSTACK_ENDPOINTS: dict[str, PaystackEndpointConfig] = {
    "Transactions": PaystackEndpointConfig(name="Transactions", path="/transaction"),
    "Customers": PaystackEndpointConfig(name="Customers", path="/customer"),
    "Subscriptions": PaystackEndpointConfig(name="Subscriptions", path="/subscription"),
    "Plans": PaystackEndpointConfig(name="Plans", path="/plan"),
    "Products": PaystackEndpointConfig(name="Products", path="/product"),
    "PaymentRequests": PaystackEndpointConfig(name="PaymentRequests", path="/paymentrequest"),
    "Settlements": PaystackEndpointConfig(name="Settlements", path="/settlement"),
    "Refunds": PaystackEndpointConfig(name="Refunds", path="/refund"),
    "Transfers": PaystackEndpointConfig(name="Transfers", path="/transfer"),
    "TransferRecipients": PaystackEndpointConfig(name="TransferRecipients", path="/transferrecipient"),
    "Disputes": PaystackEndpointConfig(name="Disputes", path="/dispute"),
    "Subaccounts": PaystackEndpointConfig(name="Subaccounts", path="/subaccount"),
    "PaymentPages": PaystackEndpointConfig(name="PaymentPages", path="/page"),
}

ENDPOINTS = tuple(PAYSTACK_ENDPOINTS.keys())
