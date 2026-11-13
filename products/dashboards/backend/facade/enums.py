"""
Shared enums for the dashboards product.

``DashboardAccessMethod`` labels how a dashboard render was reached. It lives in the facade
rather than in ``backend/access.py`` because the insight API tags its own cache metrics with
it, and a data type that crosses the product boundary belongs here.
"""

from enum import StrEnum

from posthog.enums import LabeledStrEnum


class DashboardAccessMethod(StrEnum):
    HUMAN = "human"
    SHARED = "shared"
    EMBEDDED = "embedded"
    API = "api"


class DashboardCreationMode(LabeledStrEnum):
    """How a dashboard came to exist. Mirrors `Dashboard.CreationMode`."""

    DEFAULT = "default", "Default"
    TEMPLATE = "template", "Template"
    DUPLICATE = "duplicate", "Duplicate"
    UNLISTED = "unlisted", "Unlisted (product-embedded)"


# A plain StrEnum, not a LabeledStrEnum: only the stored values cross the boundary, and the OpenAPI
# build names a component after every labeled enum it finds.
class DashboardTemplateScope(StrEnum):
    """Who can use a dashboard template. Mirrors `DashboardTemplate.Scope`."""

    ONLY_TEAM = "team"
    ORGANIZATION = "organization"
    GLOBAL = "global"
    FEATURE_FLAG = "feature_flag"


class DashboardUsageCount(StrEnum):
    """Which dashboards the usage report counts for each team."""

    ALL = "all"
    FROM_TEMPLATE = "from_template"
    SHARED = "shared"
    TAGGED = "tagged"
