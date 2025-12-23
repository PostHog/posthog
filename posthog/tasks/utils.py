# NOTE: These are the queues used for logically separating workloads.
# Many queues are consumed by one "consumer" - a worker configured to consume from that queue.
# The goal should be to split up queues based on the type of work being done, so that we can scale effectively
# and change the consumer configs without the need for code changes
#
# Worker consumers config here https://github.com/PostHog/charts/blob/main/config/posthog/prod-us.yaml.gotmpl#L538
# e.g.
#   consumers:
#     - name: priority
#       queues:
#         - email
#         - stats
#     - name: default
#       concurrency: 4
#       queues:
#         - celery # default queue for Celery
#     - name: async
#       concurrency: 4
#       queues:
#         - analytics_queries
#         - subscriptions


# NOTE: Keep in sync with bin/celery-queues.env
from enum import Enum


class CeleryQueue(Enum):
    DEFAULT = "celery"
    STATS = "stats"
    EMAIL = "email"
    LONG_RUNNING = "long_running"  # any task that has a good chance of taking more than a few seconds should go here
    ANALYTICS_QUERIES = "analytics_queries"
    ANALYTICS_LIMITED = "analytics_limited"
    ALERTS = "alerts"
    EXPORTS = "exports"
    SUBSCRIPTION_DELIVERY = "subscription_delivery"
    USAGE_REPORTS = "usage_reports"
    SESSION_REPLAY_EMBEDDINGS = "session_replay_embeddings"
    SESSION_REPLAY_PERSISTENCE = "session_replay_persistence"
    SESSION_REPLAY_GENERAL = "session_replay_general"
    INTEGRATIONS = "integrations"
