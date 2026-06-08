from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from posthog.schema import ErrorTrackingIssueAssignee

ErrorTrackingWidgetStatus = str
WidgetOrderDirection = str


class WidgetDateRange(TypedDict):
    date_from: NotRequired[str | None]


class WidgetFilterConfigEntry(TypedDict):
    filterId: str
    propertyName: str
    optionId: str
    operator: str
    value: NotRequired[str | list[str] | None]


WidgetFilterConfig = dict[str, WidgetFilterConfigEntry]


class WidgetListConfigBase(TypedDict, total=False):
    dateRange: WidgetDateRange
    filterTestAccounts: bool
    widgetFilters: WidgetFilterConfig


class WidgetListConfigInputBase(TypedDict, total=False):
    """Unvalidated widget config payload from API / JSONField before validate_* runs."""

    limit: int
    orderBy: str
    orderDirection: str
    dateRange: dict[str, object]
    filterTestAccounts: bool
    widgetFilters: dict[str, object]


class SessionReplayListWidgetConfigInput(WidgetListConfigInputBase, total=False):
    pass


class ErrorTrackingWidgetAssigneeInput(TypedDict):
    id: str | int
    type: Literal["user", "role"]


class ErrorTrackingListWidgetConfigInput(WidgetListConfigInputBase, total=False):
    status: str
    assignee: ErrorTrackingWidgetAssigneeInput | None


class SessionReplayListWidgetConfig(WidgetListConfigBase):
    limit: int
    orderBy: str
    orderDirection: WidgetOrderDirection


class ErrorTrackingListWidgetConfig(WidgetListConfigBase):
    limit: int
    orderBy: str
    orderDirection: WidgetOrderDirection
    status: ErrorTrackingWidgetStatus
    assignee: NotRequired[ErrorTrackingIssueAssignee]
