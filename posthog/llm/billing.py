AI_COST_MARKUP_PERCENT = 0.2

POSTHOG_AI_PRODUCTS = [
    "posthog_ai",
    "slack_app",
    "workflows",
    "subscriptions",
    "alert_investigation_agent",
    "alert_llm_detector",
    "product_analytics",
    "surveys",
    "replay_vision",
    "hogql_decide",
]

POSTHOG_CODE_AI_PRODUCTS = ["posthog_code"]

BILLABLE_AI_PRODUCTS = frozenset(POSTHOG_AI_PRODUCTS + POSTHOG_CODE_AI_PRODUCTS)
