DEFAULT_ACTIVITY_EVENT = {"kind": "EventsNode", "event": "$pageview", "name": "$pageview"}

# Mirrors frontend `SLACK_ARCHIVES_ORIGIN` in accountLinksLogic.ts. PostHog-internal: hardcodes our
# own workspace, so Slack links are wrong for any other team. Replace with the per-team workspace
# URL (from the conversations bot's auth.test) before GA — see COMPROMISES.md.
SLACK_ARCHIVES_ORIGIN = "https://posthog.slack.com/archives"

# Mirrors frontend `FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP`.
CUSTOMER_ANALYTICS_CSP_FLAG = "customer-analytics-csp"
CUSTOMER_ANALYTICS_FEATURE_REQUESTS_FLAG = "customer-analytics-feature-requests"
CUSTOMER_ANALYTICS_TRACK_RULES_FLAG = "customer-analytics-track-rules"

# Mirrors frontend `FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES`. Gates the whole warehouse -> person
# properties feature: creating person-target custom property sources (API + UI), staging rows during
# syncs, and the post-sync upsert workflow.
WAREHOUSE_PERSON_PROPERTIES_FLAG = "warehouse-person-properties"
WAREHOUSE_ACCOUNT_PROPERTIES_S3_SYNC_FLAG = "warehouse-account-properties-s3-sync"

# Mirrors frontend `BILLING_INSIGHT_SHORT_IDS` in accountBillingLogic.ts. These saved insights read
# warehouse-synced billing data to report an account's PostHog consumption (events ingested, rows
# synced, recordings, etc.) and spend (MRR, per-product cost). PostHog-internal: they only resolve
# in environments where the billing warehouse data exists; elsewhere the agent's lookup falls back.
BILLING_USAGE_INSIGHT_SHORT_IDS = ["fiJDsKLp"]
BILLING_SPEND_INSIGHT_SHORT_IDS = ["o4I9sdFE", "Tjo4bsux"]

CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES = [
    "text",
    "number",
    "currency",
    "percent",
    "date",
    "datetime",
    "boolean",
    "select",
]

# Mirrors OPTION_COLOR_TOKENS in the frontend's customPropertyTypes.ts (DataColorToken presets).
CUSTOM_PROPERTY_OPTION_COLORS = [f"preset-{i}" for i in range(1, 11)]

# Bounds the fan-out so one create can't enqueue an unbounded Slack send loop.
MAX_ANNOUNCEMENT_CHANNELS = 200

# Base URL for constructed Slack message permalinks (<origin>/<channel_id>/p<ts>) in account
# channel summaries. Hardcodes PostHog's workspace — pre-GA compromise, see COMPROMISES.md.
# Mirrors the frontend's SLACK_ARCHIVES_ORIGIN in accountLinksLogic.ts.
SLACK_ARCHIVES_ORIGIN = "https://posthog.slack.com/archives"

# Mirrors models.SlackSummaryCadence — kept as a plain list so the presentation layer's
# ChoiceFields stay off the model import path.
SLACK_SUMMARY_CADENCE_CHOICES = ["daily", "weekly", "monthly"]

DELIVERY_IN_FLIGHT_ERROR = "in_flight"
DELIVERY_RATE_LIMIT_DEFERRED_ERROR = "rate_limited_deferred"
DELIVERY_INTERRUPTED_ERROR = "interrupted before confirmation; the message may have been delivered"
