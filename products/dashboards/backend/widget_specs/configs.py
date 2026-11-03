from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator, model_validator

from posthog.schema import ErrorTrackingOrderBy, PropertyOperator

from products.conversations.backend.models.constants import Channel, Priority, Status
from products.dashboards.backend.constants import (
    ACTIVITY_EVENTS_DEFAULT_LIMIT,
    ACTIVITY_EVENTS_MAX_PROPERTY_FILTER_VALUES,
    ACTIVITY_EVENTS_MAX_PROPERTY_FILTERS,
    ACTIVITY_EVENTS_MAX_PROPERTY_KEY_LENGTH,
    ACTIVITY_EVENTS_MAX_PROPERTY_LABEL_LENGTH,
    ACTIVITY_EVENTS_MAX_PROPERTY_VALUE_LENGTH,
    DEFAULT_WIDGET_LIST_LIMIT,
    LOGS_LIST_DEFAULT_LIMIT,
    METRICS_TABLE_DEFAULT_LIMIT,
    METRICS_TABLE_MAX_COLUMNS,
    METRICS_TABLE_MAX_FILTERS,
    METRICS_TABLE_UNSUPPORTED_DATE_FROM_VALUES,
)
from products.dashboards.backend.widget_specs.common import (
    ActivityWidgetLimit,
    LogsWidgetLimit,
    MetricsTableWidgetLimit,
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
CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE = "conversations_recent_tickets"
NOTEBOOK_WIDGET_TYPE = "notebook_widget"
CANVAS_APP_WIDGET_TYPE = "canvas_app"
METRICS_TABLE_WIDGET_TYPE = "metrics_table"


class CanvasAppWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canvasId: UUID | None = Field(
        default=None,
        description="Canvas to render in the tile. Null until the user picks one in the widget settings.",
    )


class NotebookWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notebookShortId: str | None = Field(
        default=None, min_length=1, max_length=128, description="Source notebook short ID."
    )
    snapshotId: UUID | None = Field(
        default=None, description="Immutable notebook widget snapshot. Add one from a notebook widget's menu."
    )

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        if bool(self.notebookShortId) != bool(self.snapshotId):
            raise ValueError("Provide both the notebook and its widget snapshot.")
        return self


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
ConversationsTicketStatus = Annotated[
    str,
    WithJsonSchema({"type": "string", "enum": [*Status.values, "all"]}),
]
ConversationsTicketPriority = Annotated[
    str,
    WithJsonSchema({"type": "string", "enum": list(Priority.values)}),
]
ConversationsTicketChannel = Annotated[
    str,
    WithJsonSchema({"type": "string", "enum": [*Channel.values, "all"]}),
]


class WidgetAssigneeFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | int
    type: WidgetAssigneeType

    @model_validator(mode="before")
    @classmethod
    def validate_id(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        assignee_id = value.get("id")
        assignee_type = value.get("type")
        if isinstance(assignee_id, bool) or not isinstance(assignee_id, str | int):
            raise ValueError("Assignee id must be a user ID or role UUID.")
        if assignee_type == "user":
            try:
                int(assignee_id)
            except ValueError as err:
                raise ValueError("User assignee id must be an integer.") from err
        if assignee_type == "role":
            try:
                UUID(str(assignee_id))
            except ValueError as err:
                raise ValueError("Role assignee id must be a UUID.") from err
        return value


ConversationsAssigneeFilter = Literal["me", "unassigned"] | WidgetAssigneeFilter


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
    orderBy: ErrorTrackingOrderBy = Field(default=ErrorTrackingOrderBy.OCCURRENCES, description="Issue ranking column.")
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


class ConversationsRecentTicketsWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: WidgetLimit = Field(default=DEFAULT_WIDGET_LIST_LIMIT, description="Maximum number of tickets to return.")
    status: ConversationsTicketStatus = Field(default="all", description="Ticket status filter.")
    priorities: list[ConversationsTicketPriority] = Field(
        default_factory=list,
        description="Only show tickets with these priorities. Empty shows all priorities.",
    )
    channel: ConversationsTicketChannel = Field(default="all", description="Ticket channel filter.")
    assignees: list[ConversationsAssigneeFilter] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Only show tickets assigned to these users or roles. 'me' means the requesting user and 'unassigned' "
            "means tickets without an assignment. Empty shows all assignees."
        ),
    )
    search: str = Field(
        default="",
        max_length=200,
        description="Search requester name or email, ticket subject, message text, or ticket number.",
    )
    savedViewId: str | None = Field(
        default=None,
        max_length=12,
        description=(
            "short_id of a saved Support view to use as the source. When set, the saved view owns the ticket "
            "filters; the widget still sorts by most recently updated and applies its limit."
        ),
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {*Status.values, "all"}:
            raise ValueError("Ticket status filter is invalid.")
        return value

    @field_validator("priorities")
    @classmethod
    def validate_priorities(cls, values: list[str]) -> list[str]:
        invalid_values = set(values).difference(Priority.values)
        if invalid_values:
            raise ValueError("Ticket priority filter is invalid.")
        return values

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value not in {*Channel.values, "all"}:
            raise ValueError("Ticket channel filter is invalid.")
        return value

    @field_validator("savedViewId", mode="before")
    @classmethod
    def validate_saved_view_id(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("savedViewId must be a string.")
        return value


# `rate` and `increase` sum the per-series change of a counter, so a row shows the total for its label value.
MetricsTableAggregation = Literal["rate", "increase", "sum", "avg", "min", "max", "histogram_quantile"]
MetricsTableFilterOp = Literal["eq", "neq", "regex", "not_regex"]
MetricsTableInterval = Literal["minute", "minute_5", "minute_15", "hour", "day"]


class MetricsTableFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        min_length=1, max_length=200, description="Label key to filter on, e.g. `http.response.status_code`."
    )
    op: MetricsTableFilterOp = Field(default="eq", description="How the label value is compared.")
    value: str = Field(max_length=400, description="Label value, or a regular expression for `regex` and `not_regex`.")


class MetricsTableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40, description="Column header, e.g. `Requests/s`.")
    metricName: str = Field(min_length=1, max_length=200, description="Name of the metric this column reads.")
    aggregation: MetricsTableAggregation = Field(
        description="How each time bucket of a row is computed. `rate` and `increase` read counters."
    )
    quantile: float | None = Field(
        default=None, gt=0, lt=1, description="Required for `histogram_quantile`, e.g. 0.95 for p95."
    )
    filters: list[MetricsTableFilter] = Field(
        default_factory=list,
        max_length=METRICS_TABLE_MAX_FILTERS,
        description="Label filters for this column only, e.g. 5xx status codes for an errors column.",
    )

    @model_validator(mode="after")
    def validate_quantile(self) -> Self:
        if (self.aggregation == "histogram_quantile") != (self.quantile is not None):
            raise ValueError("Set quantile only, and always, for the histogram_quantile aggregation.")
        return self


class MetricsTableWidgetConfig(WidgetDateRangeConfigBase):
    groupBy: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Label that makes one row per value, e.g. `http.route`. Null until the user sets it.",
    )
    columns: list[MetricsTableColumn] = Field(
        default_factory=list,
        max_length=METRICS_TABLE_MAX_COLUMNS,
        description="One metric per column. Each row shows the column's average over the date range and a sparkline.",
    )
    interval: MetricsTableInterval | None = Field(
        default=None,
        description=(
            "Time between the points of the full charts that open from a row. Null picks one from the date range. "
            "The table sparklines always use at most 30 points."
        ),
    )
    orderByColumn: int = Field(default=0, ge=0, description="Index of the column that sorts the rows.")
    orderDirection: WidgetOrderDirection = Field(default="DESC", description="Sort direction for orderByColumn.")
    limit: MetricsTableWidgetLimit = Field(
        default=METRICS_TABLE_DEFAULT_LIMIT, description="Maximum number of rows to show."
    )

    @model_validator(mode="after")
    def validate_order_by_column(self) -> Self:
        if self.columns and self.orderByColumn >= len(self.columns):
            raise ValueError("orderByColumn must point to a column.")
        return self

    @model_validator(mode="after")
    def validate_metrics_query_span(self) -> Self:
        if self.dateRange is not None and self.dateRange.date_from in METRICS_TABLE_UNSUPPORTED_DATE_FROM_VALUES:
            raise ValueError("Metrics queries cover at most 30 days. Pick a shorter date range.")
        return self
