DEFAULT_ACTIVITY_EVENT = {"kind": "EventsNode", "event": "$pageview", "name": "$pageview"}

# Mirrors frontend `FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP`.
CUSTOMER_ANALYTICS_CSP_FLAG = "customer-analytics-csp"

# Mirrors frontend `BILLING_INSIGHT_SHORT_IDS` in accountBillingLogic.ts. These saved insights read
# warehouse-synced billing data to report an account's PostHog consumption (events ingested, rows
# synced, recordings, etc.) and spend (MRR, per-product cost). PostHog-internal: they only resolve
# in environments where the billing warehouse data exists; elsewhere the agent's lookup falls back.
BILLING_USAGE_INSIGHT_SHORT_IDS = ["fiJDsKLp"]
BILLING_SPEND_INSIGHT_SHORT_IDS = ["o4I9sdFE", "Tjo4bsux"]
