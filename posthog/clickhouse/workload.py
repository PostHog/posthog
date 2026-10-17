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
    NEW_EVENTS_CLUSTER = "NEW_EVENTS_CLUSTER"
    # Endpoints (the product) queries
    ENDPOINTS = "ENDPOINTS"
