from __future__ import annotations

from typing import NotRequired, TypedDict

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
