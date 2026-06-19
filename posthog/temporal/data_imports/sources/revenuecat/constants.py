CUSTOMER_RESOURCE_NAME = "customers"
PRODUCT_RESOURCE_NAME = "products"
ENTITLEMENT_RESOURCE_NAME = "entitlements"
OFFERING_RESOURCE_NAME = "offerings"
APP_RESOURCE_NAME = "apps"
EVENT_RESOURCE_NAME = "events"

# Maps PostHog schema name -> the value RevenueCat emits in `event.type` (webhook payload).
# The webhook handler uses the schema-level `webhook_resource_map` to route events into
# the corresponding warehouse table. We expose a single "events" table that captures
# every webhook event type rather than per-type tables — RevenueCat events share a flat
# schema and querying them in one table is more ergonomic.
RESOURCE_TO_REVENUECAT_EVENT_TYPE: dict[str, str] = {
    EVENT_RESOURCE_NAME: "*",
}

# Every documented RevenueCat webhook event type. Used when auto-registering the
# webhook integration so we subscribe to all known events the customer might care
# about. List is from:
# https://www.revenuecat.com/docs/integrations/webhooks/event-types-and-fields
REVENUECAT_WEBHOOK_EVENT_TYPES: tuple[str, ...] = (
    "TEST",
    "INITIAL_PURCHASE",
    "RENEWAL",
    "CANCELLATION",
    "UNCANCELLATION",
    "NON_RENEWING_PURCHASE",
    "SUBSCRIPTION_PAUSED",
    "EXPIRATION",
    "BILLING_ISSUE",
    "PRODUCT_CHANGE",
    "TRANSFER",
    "SUBSCRIPTION_EXTENDED",
    "TEMPORARY_ENTITLEMENT_GRANT",
    "REFUND_REVERSED",
    "INVOICE_ISSUANCE",
    "VIRTUAL_CURRENCY_TRANSACTION",
    "EXPERIMENT_ENROLLMENT",
)

REVENUECAT_API_BASE_URL = "https://api.revenuecat.com/v2"

# Default name applied when auto-creating the webhook integration in RevenueCat.
REVENUECAT_AUTO_WEBHOOK_NAME = "PostHog data warehouse"
