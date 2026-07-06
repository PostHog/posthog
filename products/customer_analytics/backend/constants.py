DEFAULT_ACTIVITY_EVENT = {"kind": "EventsNode", "event": "$pageview", "name": "$pageview"}

# Mirrors frontend `FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP`.
CUSTOMER_ANALYTICS_CSP_FLAG = "customer-analytics-csp"

# Account assignment roles, each assignable to a user. Shared by the external account API's
# request validation and the facade write path so the set is defined once.
ACCOUNT_ASSIGNMENT_ROLE_FIELDS = ("csm", "account_executive", "account_owner")

# Mirrors frontend `BILLING_INSIGHT_SHORT_IDS` in accountBillingLogic.ts. These saved insights read
# warehouse-synced billing data to report an account's PostHog consumption (events ingested, rows
# synced, recordings, etc.) and spend (MRR, per-product cost). PostHog-internal: they only resolve
# in environments where the billing warehouse data exists; elsewhere the agent's lookup falls back.
BILLING_USAGE_INSIGHT_SHORT_IDS = ["fiJDsKLp"]
BILLING_SPEND_INSIGHT_SHORT_IDS = ["o4I9sdFE", "Tjo4bsux"]

CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES = ["text", "number", "currency", "percent", "date", "datetime", "boolean"]

# Mirrors OPTION_COLOR_TOKENS in the frontend's customPropertyTypes.ts (DataColorToken presets).
CUSTOM_PROPERTY_OPTION_COLORS = [f"preset-{i}" for i in range(1, 11)]
