from prometheus_client import Counter, Histogram

TICKET_ACTION_AUTH_COUNTER = Counter(
    "posthog_conversations_ticket_action_auth_total",
    "Successful authentications on the ticket routes called by CDP workflow actions, by auth method",
    labelnames=["auth_method", "http_method"],  # auth_method: project_secret_api_key | scoped_jwt
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
DELIVERY_ATTEMPTS_TOTAL = Counter(
    "posthog_conversations_delivery_attempts_total",
    "Outbound delivery-part processing attempts by part key and result",
    labelnames=["part_key", "result"],  # claimed | retry | deferred | accepted | failed
)
DELIVERY_LEASES_TOTAL = Counter(
    "posthog_conversations_delivery_leases_total",
    "Outbound delivery-part lease outcomes",
    labelnames=["result"],  # claimed | expired_reclaim | busy
)
