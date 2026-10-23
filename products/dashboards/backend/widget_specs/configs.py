from __future__ import annotations

from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from posthog.schema import ErrorTrackingOrderBy, MetricsQuery, MetricsQueryClause, PropertyOperator

from posthog.schema_migrations.upgrade import upgrade

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
    METRICS_WIDGET_MAX_CLAUSES,
    METRICS_WIDGET_MAX_QUERY_JSON_LENGTH,
    METRICS_WIDGET_MAX_QUERY_TEXT_LENGTH,
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
CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE = "conversations_recent_tickets"
NOTEBOOK_WIDGET_TYPE = "notebook_widget"
CANVAS_APP_WIDGET_TYPE = "canvas_app"
METRICS_WIDGET_TYPE = "metrics"


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


class MetricsWidgetQuery(MetricsQuery):
    """A `MetricsQuery` as a metrics widget stores it.

    Response, modifier and tag fields are runtime state, so a stored config can't carry them.
    """

    clauses: list[MetricsQueryClause] = Field(
        default_factory=list,
        max_length=METRICS_WIDGET_MAX_CLAUSES,
        description="Builder series. Empty when `language` is `promql` or `sql`, or until a metric is picked.",
    )
    promql: str | None = Field(
        default=None,
        max_length=METRICS_WIDGET_MAX_QUERY_TEXT_LENGTH,
        description="PromQL expression, run as a range query. Used when `language` is `promql`.",
    )
    sql: str | None = Field(
        default=None,
        max_length=METRICS_WIDGET_MAX_QUERY_TEXT_LENGTH,
        description=(
            "HogQL SELECT over the posthog.metric* tables. Used when `language` is `sql`. It must return a `time` "
            "and a `value` column; every other column is a series label."
        ),
    )
    response: SkipJsonSchema[None] = None
    modifiers: SkipJsonSchema[None] = None
    tags: SkipJsonSchema[None] = None
    # Variable definitions hold their own SQL or PromQL, and widgets don't take dashboard variables yet.
    variables: SkipJsonSchema[None] = None

    @model_validator(mode="after")
    def cap_stored_size(self) -> Self:
        # Every dashboard read returns the config, so filters, formulas and display settings share one size cap.
        if len(self.model_dump_json(exclude_none=True)) > METRICS_WIDGET_MAX_QUERY_JSON_LENGTH:
            raise ValueError(f"The query is larger than {METRICS_WIDGET_MAX_QUERY_JSON_LENGTH} characters.")
        return self


class MetricsWidgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: MetricsWidgetQuery = Field(
        default_factory=MetricsWidgetQuery,
        description=(
            "Metrics query the tile runs and how it draws it (`display.type`: line, area, bar, stat, gauge, "
            "bargauge, table or heatmap). `dateRange` is the default window; the dashboard date filter overrides "
            "it. A config update replaces the whole query."
        ),
    )

    @field_validator("query", mode="before")
    @classmethod
    def upgrade_query(cls, value: Any) -> Any:
        # Saved insight queries migrate through the same upgrade on read, so stored widgets survive schema changes.
        # The migration walker keys on `kind`, so anything but the metrics kind goes straight to validation.
        if not (isinstance(value, dict) and value.get("kind") == "MetricsQuery"):
            return value
        try:
            return upgrade(value)
        except (TypeError, KeyError, AttributeError, ValueError) as error:
            # A malformed nested node must fail validation, not reach the client as a server error.
            raise ValueError("The query has a node that can't be read.") from error
