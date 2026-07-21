from enum import StrEnum


class Workload(StrEnum):
    # Default workload
    DEFAULT = "DEFAULT"
    # Analytics queries, other 'lively' queries
    ONLINE = "ONLINE"
    # Historical exports, other long-running processes where latency is less critical
    OFFLINE = "OFFLINE"
    # Logs queries
    LOGS = "LOGS"
    # Endpoints (the product) queries
    ENDPOINTS = "ENDPOINTS"
    # Materialized-view-only reads, offloaded to the endpoints cluster. Shares that cluster's host but
    # stays a distinct label so it isn't conflated with Endpoints-product traffic in query_log / metrics
    # and doesn't inherit endpoints-specific rate limiting.
    MATERIALIZED_VIEWS = "MATERIALIZED_VIEWS"
