from enum import StrEnum


class Workload(StrEnum):
    DEFAULT = "DEFAULT"
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    LOGS = "LOGS"
    ENDPOINTS = "ENDPOINTS"
