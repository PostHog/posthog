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


# Keep the labels equal to those of `DashboardTemplate.Scope`. The OpenAPI build names the
# `DashboardTemplateScopeEnum` component after the two classes only while they hold the same choices.
class DashboardTemplateScope(LabeledStrEnum):
    """Who can use a dashboard template. Mirrors `DashboardTemplate.Scope`."""

    ONLY_TEAM = "team", "Only team"
    ORGANIZATION = "organization", "Organization"
    GLOBAL = "global", "Global"
    FEATURE_FLAG = "feature_flag", "Feature Flag"


class DashboardTemplateOrdering(StrEnum):
    """How the template list sorts after featured templates. A search sorts by relevance instead."""

    NAME = "template_name"
    NAME_DESCENDING = "-template_name"
    CREATED_AT = "created_at"
    CREATED_AT_DESCENDING = "-created_at"


class DashboardUsageCount(StrEnum):
    """Which dashboards the usage report counts for each team."""

    ALL = "all"
    FROM_TEMPLATE = "from_template"
    SHARED = "shared"
    TAGGED = "tagged"


class QueryBatchLanguage(LabeledStrEnum):
    """What a query batch target's `query` text holds."""

    INSIGHT = "insight", "Insight"
    HOGQL = "hogql", "HogQL"
    PROMQL = "promql", "PromQL"
    LOGQL = "logql", "LogQL"
