from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from posthog.schema import PropertyOperator

from products.dashboards.backend.constants import (
    ACTIVITY_EVENTS_DEFAULT_LIMIT,
    ACTIVITY_EVENTS_MAX_PROPERTY_FILTER_VALUES,
    ACTIVITY_EVENTS_MAX_PROPERTY_FILTERS,
    ACTIVITY_EVENTS_MAX_PROPERTY_KEY_LENGTH,
    ACTIVITY_EVENTS_MAX_PROPERTY_LABEL_LENGTH,
    ACTIVITY_EVENTS_MAX_PROPERTY_VALUE_LENGTH,
    DEFAULT_WIDGET_LIST_LIMIT,
    LOGS_LIST_DEFAULT_LIMIT,
)
from products.dashboards.backend.widget_specs.common import (
    ActivityWidgetLimit,
    LogsWidgetLimit,
    WidgetDateRange,
    WidgetDateRangeConfigBase,
    WidgetLimit,
    WidgetListConfigBase,
    WidgetOrderDirection,
)

ACTIVITY_EVENTS_LIST_WIDGET_TYPE = "activity_events_list"
ERROR_TRACKING_LIST_WIDGET_TYPE = "error_tracking_list"
SESSION_REPLAY_LIST_WIDGET_TYPE = "session_replay_list"
EXPERIMENTS_LIST_WIDGET_TYPE = "experiments_list"
EXPERIMENT_RESULTS_WIDGET_TYPE = "experiment_results"
SURVEY_RESULTS_WIDGET_TYPE = "survey_results"
LOGS_LIST_WIDGET_TYPE = "logs_list"

ActivityEventsPropertyKey = Annotated[
    str,
    Field(min_length=1, max_length=ACTIVITY_EVENTS_MAX_PROPERTY_KEY_LENGTH),
]
ActivityEventsPropertyLabel = Annotated[str, Field(max_length=ACTIVITY_EVENTS_MAX_PROPERTY_LABEL_LENGTH)]
ActivityEventsPropertyStringValue = Annotated[str, Field(max_length=ACTIVITY_EVENTS_MAX_PROPERTY_VALUE_LENGTH)]
ActivityEventsPropertyScalar = ActivityEventsPropertyStringValue | float | bool
ActivityEventsPropertyValues = Annotated[
    list[ActivityEventsPropertyScalar],
    Field(max_length=ACTIVITY_EVENTS_MAX_PROPERTY_FILTER_VALUES),
]

ErrorTrackingOrderBy = Literal["last_seen", "first_seen", "occurrences", "users", "sessions"]
ErrorTrackingWidgetStatus = Literal["archived", "active", "resolved", "pending_release", "suppressed", "all"]
SessionReplayOrderBy = Literal[
    "start_time", "activity_score", "recording_duration", "duration", "click_count", "console_error_count"
]
WidgetAssigneeType = Literal["user", "role"]
ExperimentsWidgetStatus = Literal["draft", "running", "paused", "exposure_frozen", "stopped", "all"]
ExperimentsWidgetOrderBy = Literal["created_at", "name", "start_date"]
# Matches the logs scene: `earliest` sorts ascending by timestamp, `latest` (default) descending.
LogsOrderBy = Literal["latest", "earliest"]
LogSeverityLevel = Literal["trace", "debug", "info", "warn", "error", "fatal"]
# How log timestamps render on the tile: in UTC, or in each viewer's local timezone.
LogsTimezone = Literal["UTC", "local"]


class WidgetAssigneeFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | int
    type: WidgetAssigneeType


class ActivityEventsPropertyFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: ActivityEventsPropertyKey
    label: ActivityEventsPropertyLabel | None = None
    operator: PropertyOperator
    type: Literal["event", "person"]
    value: ActivityEventsPropertyValues | ActivityEventsPropertyScalar | None = None

    @model_validator(mode="after")
    def validate_operator_value(self) -> Self:
        if self.operator == PropertyOperator.FLAG_EVALUATES_TO:
            raise ValueError("flag_evaluates_to is only valid for feature flag filters.")
        if self.operator in {PropertyOperator.IN_, PropertyOperator.NOT_IN} and not isinstance(self.value, list):
            raise ValueError(f"{self.operator.value} requires a list of values.")
        if self.operator in {PropertyOperator.BETWEEN, PropertyOperator.NOT_BETWEEN} and (
            not isinstance(self.value, list) or len(self.value) != 2
        ):
            raise ValueError(f"{self.operator.value} requires exactly two values.")
        if self.operator in {
            PropertyOperator.IS_DATE_EXACT,
            PropertyOperator.IS_DATE_BEFORE,
            PropertyOperator.IS_DATE_AFTER,
            PropertyOperator.REGEX,
            PropertyOperator.NOT_REGEX,
        } and not isinstance(self.value, str):
            raise ValueError(f"{self.operator.value} requires a string value.")
        return self


class ErrorTrackingListWidgetConfig(WidgetListConfigBase):
    limit: WidgetLimit = Field(default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of issues to return.")
    orderBy: ErrorTrackingOrderBy = Field(default="occurrences", description="Issue ranking column.")
    orderDirection: WidgetOrderDirection = Field(default="DESC", description="Sort direction for orderBy.")
    status: ErrorTrackingWidgetStatus = Field(default="active", description="Issue status filter.")
    assignee: WidgetAssigneeFilter | None = Field(
        default=None,
        description="Filter by assignee ({type: user|role, id}). Omit for any assignee.",
    )


class SessionReplayListWidgetConfig(WidgetListConfigBase):
    limit: WidgetLimit = Field(default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of recordings to return.")
    orderBy: SessionReplayOrderBy = Field(default="start_time", description="Recording ranking column.")
    orderDirection: WidgetOrderDirection = Field(default="DESC", description="Sort direction for orderBy.")
    savedFilterId: str | None = Field(
        default=None,
        description=(
            "short_id of a saved session replay filter to refine the recordings shown. When set, the saved filter "
            "owns the date range and property filters; only orderBy, orderDirection, and limit still apply. Combine "
            "with collectionId to filter within a collection."
        ),
    )
    collectionId: str | None = Field(
        default=None,
        description=(
            "short_id of a session replay collection to scope the widget to its pinned recordings. Combine with "
            "savedFilterId or property filters to narrow within the collection; orderBy, orderDirection, and limit "
            "still apply."
        ),
    )

    @field_validator("savedFilterId", "collectionId", mode="before")
    @classmethod
    def validate_short_id(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("must be a string.")
        return value


class ActivityEventsListWidgetConfig(WidgetListConfigBase):
    limit: ActivityWidgetLimit = Field(
        default=ACTIVITY_EVENTS_DEFAULT_LIMIT, description="Maximum number of events to return."
    )
    eventName: str | None = Field(
        default=None,
        min_length=1,
        description="Limit the feed to a single event name. Omit or null for all events.",
    )
    properties: list[ActivityEventsPropertyFilter] | None = Field(
        default=None,
        max_length=ACTIVITY_EVENTS_MAX_PROPERTY_FILTERS,
        description="Event and person property filters, matching Activity > Explore events.",
    )


class ExperimentsListWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: WidgetLimit = Field(
        default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of experiments to return."
    )
    orderBy: ExperimentsWidgetOrderBy = Field(default="created_at", description="Experiment list sort column.")
    orderDirection: WidgetOrderDirection = Field(default="DESC", description="Sort direction for orderBy.")
    status: ExperimentsWidgetStatus = Field(default="all", description="Experiment status filter.")
    createdBy: int | None = Field(default=None, description="Filter by creator (user id). Omit for any creator.")


class ExperimentResultsWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experimentId: int | None = Field(
        default=None,
        description="Experiment to show results for. Null until the user picks one in the widget settings.",
    )


class SurveyResultsWidgetConfig(WidgetDateRangeConfigBase):
    dateRange: WidgetDateRange | None = Field(
        default=None, description="Null or omitted means all time (the survey's full lifetime)."
    )
    surveyId: str | None = Field(
        default=None,
        description="Survey to show performance stats and recent responses for. Null until the user picks one.",
    )
    limit: WidgetLimit = Field(
        default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of recent responses to return."
    )

    @field_validator("surveyId", mode="before")
    @classmethod
    def validate_survey_id(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("surveyId must be a string.")
        return value


class LogsListWidgetConfig(WidgetDateRangeConfigBase):
    limit: LogsWidgetLimit = Field(
        default=LOGS_LIST_DEFAULT_LIMIT, description="Maximum number of log lines to return."
    )
    orderBy: LogsOrderBy = Field(default="latest", description="Sort by newest (latest) or oldest (earliest) first.")
    severityLevels: list[LogSeverityLevel] = Field(
        default_factory=list,
        description="Only show logs at these severity levels. Empty shows all levels.",
    )
    serviceNames: list[str] = Field(
        default_factory=list,
        description="Only show logs from these services. Empty shows all services.",
    )
    wrapLines: bool = Field(
        default=False,
        description="Wrap long log lines instead of truncating them to a single row.",
    )
    timezone: LogsTimezone = Field(
        default="UTC",
        description="Render log timestamps in UTC or in each viewer's local timezone.",
    )
    savedViewId: str | None = Field(
        default=None,
        description=(
            "short_id of a saved logs view to use as the source. When set, the saved view owns the date range, "
            "severity, service, and property filters; only orderBy and limit still apply."
        ),
    )

    @field_validator("savedViewId", mode="before")
    @classmethod
    def validate_saved_view_id(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("savedViewId must be a string.")
        return value
