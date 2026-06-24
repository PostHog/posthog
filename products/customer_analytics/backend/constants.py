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

# PostHog-internal billing warehouse view (one row per org per invoice period), keyed by
# organization_id (== an account's external_id). Backs the optional, picker-only `confirmed_mrr`
# and `credits_used` account columns. Like the billing insights above, it only exists in
# environments with the billing warehouse data; the account columns resolve to NULL elsewhere.
# Mirrors the frontend constants in components/Accounts/constants.ts.
BILLING_INVOICES_VIEW_NAME = "billing_invoices_by_org"
BILLING_CONFIRMED_MRR_COLUMN = "confirmed_mrr"
BILLING_CREDITS_USED_COLUMN = "credits_used"
BILLING_PICKER_COLUMNS = (BILLING_CONFIRMED_MRR_COLUMN, BILLING_CREDITS_USED_COLUMN)

CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES = ["text", "number", "currency", "percent", "date", "datetime", "boolean"]
