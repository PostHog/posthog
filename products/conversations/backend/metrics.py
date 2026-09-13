from prometheus_client import Counter, Histogram

# Cutover observability for #82564: the CDP worker's ticket actions move from
# secret_api_token on the external route to scoped JWTs on the internal route.
# The legacy worker path can be removed once auth_method="secret_api_token" stays at zero.
TICKET_ACTION_AUTH_COUNTER = Counter(
    "posthog_conversations_ticket_action_auth_total",
    "Successful authentications on the ticket routes called by CDP workflow actions, by auth method",
    labelnames=["auth_method", "http_method"],  # auth_method: secret_api_token | scoped_jwt
)

TICKET_SEARCH_DURATION_SECONDS = Histogram(
    "posthog_support_ticket_search_duration_seconds",
    "End-to-end duration of support ticket list requests that include a search term",
    labelnames=["search_path"],  # ticket_number | text
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, float("inf")),
)

INBOUND_ATTEMPTS_TOTAL = Counter(
    "posthog_conversations_inbound_attempts_total",
    "Inbound receipt processing attempts by source and result",
    labelnames=["source", "result"],  # processed | retry | failed | claimed
)
INBOUND_LEASES_TOTAL = Counter(
    "posthog_conversations_inbound_leases_total",
    "Inbound receipt lease outcomes",
    labelnames=["result"],  # claimed | expired_reclaim | busy | renewed | renew_rejected
)
