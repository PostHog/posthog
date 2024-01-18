# NOTE: These are the queues used for logically separating workloads.
# Many queues are consumed by one "consumer" - a worker configured to consume from that queue.
# The goal should be to split up queues based on the type of work being done, so that we can scale effectively
# and change the consumer configs without the need for code changes
#
# Worker consumers config here https://github.com/PostHog/posthog-cloud-infra/blob/main/helm/values/prod.yml#L368
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
class CeleryQueue:
    DEFAULT = "celery"
    STATS = "stats"
    EMAIL = "email"
    INSIGHT_EXPORT = "insight_export"
    INSIGHT_REFRESH = "insight_refresh"
    ANALYTICS_QUERIES = "analytics_queries"
    EXPORTS = "exports"
    SUBSCRIPTION_DELIVERY = "subscription_delivery"
