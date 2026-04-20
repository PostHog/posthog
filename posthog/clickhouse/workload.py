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
