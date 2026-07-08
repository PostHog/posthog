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
#
# This module must stay import-light: queue names are needed at decorator-eval time by
# modules that load during django.setup(), and the posthog.tasks package (the enum's old
# home) eagerly imports every task module on first touch.

# NOTE: Keep in sync with bin/celery-queues.env
from enum import Enum


class CeleryQueue(Enum):
    DEFAULT = "celery"
    STATS = "stats"
    EMAIL = "email"
    LONG_RUNNING = "long_running"  # any task that has a good chance of taking more than a few seconds should go here
    ANALYTICS_QUERIES = "analytics_queries"
    ANALYTICS_LIMITED = "analytics_limited"
    EXPORTS = "exports"
    SUBSCRIPTION_DELIVERY = "subscription_delivery"
    USAGE_REPORTS = "usage_reports"
    INTEGRATIONS = "integrations"
    FEATURE_FLAGS = "feature_flags"
    FEATURE_FLAGS_LONG_RUNNING = "feature_flags_long_running"
