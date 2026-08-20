"""
Shared enums for the dashboards product.

``DashboardAccessMethod`` labels how a dashboard render was reached. It lives in the facade
rather than in ``backend/access.py`` because the insight API tags its own cache metrics with
it, and a data type that crosses the product boundary belongs here.
"""

from enum import StrEnum


class DashboardAccessMethod(StrEnum):
    HUMAN = "human"
    SHARED = "shared"
    EMBEDDED = "embedded"
    API = "api"
