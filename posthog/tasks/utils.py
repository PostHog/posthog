from enum import Enum


# NOTE: Keep in sync with bin/celery-queues.env
class CeleryQueue(Enum):
    DEFAULT = "celery"
    EMAIL = "email"
    INSIGHT_EXPORT = "insight_export"
    INSIGHT_REFRESH = "insight_refresh"
    ANALYTICS_QUERIES = "analytics_queries"
    # EXPORTS = "exports"
