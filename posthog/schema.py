# mypy: disable-error-code="assignment"

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel


class SchemaRoot(RootModel[Any]):
    root: Any


class MathGroupTypeIndex(float, Enum):
    NUMBER_0 = 0
    NUMBER_1 = 1
    NUMBER_2 = 2
    NUMBER_3 = 3
    NUMBER_4 = 4


class AggregationAxisFormat(str, Enum):
    NUMERIC = "numeric"
    DURATION = "duration"
    DURATION_MS = "duration_ms"
    PERCENTAGE = "percentage"
    PERCENTAGE_SCALED = "percentage_scaled"


class Kind(str, Enum):
    METHOD = "Method"
    FUNCTION = "Function"
    CONSTRUCTOR = "Constructor"
    FIELD = "Field"
    VARIABLE = "Variable"
    CLASS_ = "Class"
    STRUCT = "Struct"
    INTERFACE = "Interface"
    MODULE = "Module"
    PROPERTY = "Property"
    EVENT = "Event"
    OPERATOR = "Operator"
    UNIT = "Unit"
    VALUE = "Value"
    CONSTANT = "Constant"
    ENUM = "Enum"
    ENUM_MEMBER = "EnumMember"
    KEYWORD = "Keyword"
    TEXT = "Text"
    COLOR = "Color"
    FILE = "File"
    REFERENCE = "Reference"
    CUSTOMCOLOR = "Customcolor"
    FOLDER = "Folder"
    TYPE_PARAMETER = "TypeParameter"
    USER = "User"
    ISSUE = "Issue"
    SNIPPET = "Snippet"


class AutocompleteCompletionItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    detail: Optional[str] = Field(
        default=None,
        description=(
            "A human-readable string with additional information about this item, like type or symbol information."
        ),
    )
    documentation: Optional[str] = Field(
        default=None, description="A human-readable string that represents a doc-comment."
    )
    insert_text: str = Field(
        ...,
        alias="insertText",
        description="A string or snippet that should be inserted in a document when selecting this completion.",
    )
    kind: Kind = Field(
        ..., description="The kind of this completion item. Based on the kind an icon is chosen by the editor."
    )
    label: str = Field(
        ...,
        description=(
            "The label of this completion item. By default this is also the text that is inserted when selecting this"
            " completion."
        ),
    )


class BaseMathType(str, Enum):
    TOTAL = "total"
    DAU = "dau"
    WEEKLY_ACTIVE = "weekly_active"
    MONTHLY_ACTIVE = "monthly_active"
    UNIQUE_SESSION = "unique_session"


class BreakdownAttributionType(str, Enum):
    FIRST_TOUCH = "first_touch"
    LAST_TOUCH = "last_touch"
    ALL_EVENTS = "all_events"
    STEP = "step"


class BreakdownType(str, Enum):
    COHORT = "cohort"
    PERSON = "person"
    EVENT = "event"
    GROUP = "group"
    SESSION = "session"
    HOGQL = "hogql"
    DATA_WAREHOUSE = "data_warehouse"
    DATA_WAREHOUSE_PERSON_PROPERTY = "data_warehouse_person_property"


class BreakdownValueInt(RootModel[int]):
    root: int


class BreakdownItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: Union[str, int]


class CompareItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: str


class IntervalItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: int = Field(..., description="An interval selected out of available intervals in source query")


class Series(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: int


class StatusItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: str


class ChartAxis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    column: str


class ChartDisplayType(str, Enum):
    ACTIONS_LINE_GRAPH = "ActionsLineGraph"
    ACTIONS_BAR = "ActionsBar"
    ACTIONS_AREA_GRAPH = "ActionsAreaGraph"
    ACTIONS_LINE_GRAPH_CUMULATIVE = "ActionsLineGraphCumulative"
    BOLD_NUMBER = "BoldNumber"
    ACTIONS_PIE = "ActionsPie"
    ACTIONS_BAR_VALUE = "ActionsBarValue"
    ACTIONS_TABLE = "ActionsTable"
    WORLD_MAP = "WorldMap"


class ClickhouseQueryProgress(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active_cpu_time: int
    bytes_read: int
    estimated_rows_total: int
    rows_read: int
    time_elapsed: int


class CohortPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Literal["id"] = "id"
    label: Optional[str] = None
    type: Literal["cohort"] = "cohort"
    value: int


class CountPerActorMathType(str, Enum):
    AVG_COUNT_PER_ACTOR = "avg_count_per_actor"
    MIN_COUNT_PER_ACTOR = "min_count_per_actor"
    MAX_COUNT_PER_ACTOR = "max_count_per_actor"
    MEDIAN_COUNT_PER_ACTOR = "median_count_per_actor"
    P90_COUNT_PER_ACTOR = "p90_count_per_actor"
    P95_COUNT_PER_ACTOR = "p95_count_per_actor"
    P99_COUNT_PER_ACTOR = "p99_count_per_actor"


class Response3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: list[dict[str, Any]]


class DataWarehouseEventsModifier(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_id_field: str
    id_field: str
    table_name: str
    timestamp_field: str


class DatabaseSchemaSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    incremental: bool
    last_synced_at: Optional[str] = None
    name: str
    should_sync: bool
    status: str


class DatabaseSchemaSource(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    last_synced_at: Optional[str] = None
    prefix: str
    source_type: str
    status: str


class Type(str, Enum):
    POSTHOG = "posthog"
    DATA_WAREHOUSE = "data_warehouse"
    VIEW = "view"


class DatabaseSerializedFieldType(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    DATETIME = "datetime"
    DATE = "date"
    BOOLEAN = "boolean"
    ARRAY = "array"
    JSON = "json"
    LAZY_TABLE = "lazy_table"
    VIRTUAL_TABLE = "virtual_table"
    FIELD_TRAVERSER = "field_traverser"
    EXPRESSION = "expression"
    VIEW = "view"


class DateRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    explicit_date: Optional[bool] = Field(
        default=False,
        alias="explicitDate",
        description=(
            "Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of"
            " period."
        ),
    )


class DatetimeDay(RootModel[AwareDatetime]):
    root: AwareDatetime


class Day(RootModel[int]):
    root: int


class DurationType(str, Enum):
    DURATION = "duration"
    ACTIVE_SECONDS = "active_seconds"
    INACTIVE_SECONDS = "inactive_seconds"


class Key(str, Enum):
    TAG_NAME = "tag_name"
    TEXT = "text"
    HREF = "href"
    SELECTOR = "selector"


class ElementType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    attr_class: Optional[list[str]] = None
    attr_id: Optional[str] = None
    attributes: dict[str, str]
    href: Optional[str] = None
    nth_child: Optional[float] = None
    nth_of_type: Optional[float] = None
    order: Optional[float] = None
    tag_name: str
    text: Optional[str] = None


class EmptyPropertyFilter(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class EntityType(str, Enum):
    ACTIONS = "actions"
    EVENTS = "events"
    DATA_WAREHOUSE = "data_warehouse"
    NEW_ENTITY = "new_entity"


class EventDefinition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    elements: list
    event: str
    properties: dict[str, Any]


class CorrelationType(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"


class EventOddsRatioSerialized(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    correlation_type: CorrelationType
    event: EventDefinition
    failure_count: int
    odds_ratio: float
    success_count: int


class Person(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_ids: list[str]
    is_identified: Optional[bool] = None
    properties: dict[str, Any]


class EventType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_id: str
    elements: list[ElementType]
    elements_chain: Optional[str] = None
    event: str
    id: str
    person: Optional[Person] = None
    properties: dict[str, Any]
    timestamp: str
    uuid: Optional[str] = None


class Properties(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    email: Optional[str] = None
    name: Optional[str] = None


class EventsQueryPersonColumn(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created_at: str
    distinct_id: str
    properties: Properties
    uuid: str


class FilterLogicalOperator(str, Enum):
    AND_ = "AND"
    OR_ = "OR"


class FunnelConversionWindowTimeUnit(str, Enum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class FunnelCorrelationResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[EventOddsRatioSerialized]
    skewed: bool


class FunnelCorrelationResultsType(str, Enum):
    EVENTS = "events"
    PROPERTIES = "properties"
    EVENT_WITH_PROPERTIES = "event_with_properties"


class FunnelExclusionLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    funnel_from_step: float
    funnel_to_step: float
    id: Optional[Union[str, float]] = None
    index: Optional[float] = None
    name: Optional[str] = None
    order: Optional[float] = None
    type: Optional[EntityType] = None


class FunnelExclusionSteps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_from_step: int = Field(..., alias="funnelFromStep")
    funnel_to_step: int = Field(..., alias="funnelToStep")


class FunnelLayout(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class FunnelPathType(str, Enum):
    FUNNEL_PATH_BEFORE_STEP = "funnel_path_before_step"
    FUNNEL_PATH_BETWEEN_STEPS = "funnel_path_between_steps"
    FUNNEL_PATH_AFTER_STEP = "funnel_path_after_step"


class FunnelStepReference(str, Enum):
    TOTAL = "total"
    PREVIOUS = "previous"


class FunnelTimeToConvertResults(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    average_conversion_time: Optional[float] = None
    bins: list[list[int]]


class FunnelVizType(str, Enum):
    STEPS = "steps"
    TIME_TO_CONVERT = "time_to_convert"
    TRENDS = "trends"


class GoalLine(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: float


class HogQLNotice(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    end: Optional[int] = None
    fix: Optional[str] = None
    message: str
    start: Optional[int] = None


class BounceRatePageViewMode(str, Enum):
    COUNT_PAGEVIEWS = "count_pageviews"
    UNIQ_URLS = "uniq_urls"


class InCohortVia(str, Enum):
    AUTO = "auto"
    LEFTJOIN = "leftjoin"
    SUBQUERY = "subquery"
    LEFTJOIN_CONJOINED = "leftjoin_conjoined"


class MaterializationMode(str, Enum):
    AUTO = "auto"
    LEGACY_NULL_AS_STRING = "legacy_null_as_string"
    LEGACY_NULL_AS_NULL = "legacy_null_as_null"
    DISABLED = "disabled"


class PersonsArgMaxVersion(str, Enum):
    AUTO = "auto"
    V1 = "v1"
    V2 = "v2"


class PersonsJoinMode(str, Enum):
    INNER = "inner"
    LEFT = "left"


class PersonsOnEventsMode(str, Enum):
    DISABLED = "disabled"
    PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS = "person_id_no_override_properties_on_events"
    PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS = "person_id_override_properties_on_events"
    PERSON_ID_OVERRIDE_PROPERTIES_JOINED = "person_id_override_properties_joined"


class HogQLQueryModifiers(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bounce_rate_page_view_mode: Optional[BounceRatePageViewMode] = Field(default=None, alias="bounceRatePageViewMode")
    data_warehouse_events_modifiers: Optional[list[DataWarehouseEventsModifier]] = Field(
        default=None, alias="dataWarehouseEventsModifiers"
    )
    debug: Optional[bool] = None
    in_cohort_via: Optional[InCohortVia] = Field(default=None, alias="inCohortVia")
    materialization_mode: Optional[MaterializationMode] = Field(default=None, alias="materializationMode")
    optimize_joined_filters: Optional[bool] = Field(default=None, alias="optimizeJoinedFilters")
    persons_arg_max_version: Optional[PersonsArgMaxVersion] = Field(default=None, alias="personsArgMaxVersion")
    persons_join_mode: Optional[PersonsJoinMode] = Field(default=None, alias="personsJoinMode")
    persons_on_events_mode: Optional[PersonsOnEventsMode] = Field(default=None, alias="personsOnEventsMode")
    s3_table_use_invalid_columns: Optional[bool] = Field(default=None, alias="s3TableUseInvalidColumns")


class HogQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: Optional[list] = None
    results: Any
    stdout: Optional[str] = None


class Compare(str, Enum):
    CURRENT = "current"
    PREVIOUS = "previous"


class DayItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: Union[str, AwareDatetime, int]


class InsightActorsQueryOptionsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[list[BreakdownItem]] = None
    compare: Optional[list[CompareItem]] = None
    day: Optional[list[DayItem]] = None
    interval: Optional[list[IntervalItem]] = None
    series: Optional[list[Series]] = None
    status: Optional[list[StatusItem]] = None


class InsightDateRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = "-7d"
    date_to: Optional[str] = None
    explicit_date: Optional[bool] = Field(
        default=False,
        alias="explicitDate",
        description=(
            "Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of"
            " period."
        ),
    )


class InsightFilterProperty(str, Enum):
    TRENDS_FILTER = "trendsFilter"
    FUNNELS_FILTER = "funnelsFilter"
    RETENTION_FILTER = "retentionFilter"
    PATHS_FILTER = "pathsFilter"
    STICKINESS_FILTER = "stickinessFilter"
    LIFECYCLE_FILTER = "lifecycleFilter"


class InsightNodeKind(str, Enum):
    TRENDS_QUERY = "TrendsQuery"
    FUNNELS_QUERY = "FunnelsQuery"
    RETENTION_QUERY = "RetentionQuery"
    PATHS_QUERY = "PathsQuery"
    STICKINESS_QUERY = "StickinessQuery"
    LIFECYCLE_QUERY = "LifecycleQuery"


class InsightType(str, Enum):
    TRENDS = "TRENDS"
    STICKINESS = "STICKINESS"
    LIFECYCLE = "LIFECYCLE"
    FUNNELS = "FUNNELS"
    RETENTION = "RETENTION"
    PATHS = "PATHS"
    JSON = "JSON"
    SQL = "SQL"
    HOG = "HOG"


class IntervalType(str, Enum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class LifecycleToggle(str, Enum):
    NEW = "new"
    RESURRECTING = "resurrecting"
    RETURNING = "returning"
    DORMANT = "dormant"


class NodeKind(str, Enum):
    EVENTS_NODE = "EventsNode"
    ACTIONS_NODE = "ActionsNode"
    DATA_WAREHOUSE_NODE = "DataWarehouseNode"
    EVENTS_QUERY = "EventsQuery"
    PERSONS_NODE = "PersonsNode"
    HOG_QUERY = "HogQuery"
    HOG_QL_QUERY = "HogQLQuery"
    HOG_QL_METADATA = "HogQLMetadata"
    HOG_QL_AUTOCOMPLETE = "HogQLAutocomplete"
    ACTORS_QUERY = "ActorsQuery"
    FUNNELS_ACTORS_QUERY = "FunnelsActorsQuery"
    FUNNEL_CORRELATION_ACTORS_QUERY = "FunnelCorrelationActorsQuery"
    SESSIONS_TIMELINE_QUERY = "SessionsTimelineQuery"
    DATA_TABLE_NODE = "DataTableNode"
    DATA_VISUALIZATION_NODE = "DataVisualizationNode"
    SAVED_INSIGHT_NODE = "SavedInsightNode"
    INSIGHT_VIZ_NODE = "InsightVizNode"
    TRENDS_QUERY = "TrendsQuery"
    FUNNELS_QUERY = "FunnelsQuery"
    RETENTION_QUERY = "RetentionQuery"
    PATHS_QUERY = "PathsQuery"
    STICKINESS_QUERY = "StickinessQuery"
    LIFECYCLE_QUERY = "LifecycleQuery"
    INSIGHT_ACTORS_QUERY = "InsightActorsQuery"
    INSIGHT_ACTORS_QUERY_OPTIONS = "InsightActorsQueryOptions"
    FUNNEL_CORRELATION_QUERY = "FunnelCorrelationQuery"
    WEB_OVERVIEW_QUERY = "WebOverviewQuery"
    WEB_TOP_CLICKS_QUERY = "WebTopClicksQuery"
    WEB_STATS_TABLE_QUERY = "WebStatsTableQuery"
    TIME_TO_SEE_DATA_SESSIONS_QUERY = "TimeToSeeDataSessionsQuery"
    TIME_TO_SEE_DATA_QUERY = "TimeToSeeDataQuery"
    TIME_TO_SEE_DATA_SESSIONS_JSON_NODE = "TimeToSeeDataSessionsJSONNode"
    TIME_TO_SEE_DATA_SESSIONS_WATERFALL_NODE = "TimeToSeeDataSessionsWaterfallNode"
    DATABASE_SCHEMA_QUERY = "DatabaseSchemaQuery"


class PathCleaningFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    alias: Optional[str] = None
    regex: Optional[str] = None


class PathType(str, Enum):
    FIELD_PAGEVIEW = "$pageview"
    FIELD_SCREEN = "$screen"
    CUSTOM_EVENT = "custom_event"
    HOGQL = "hogql"


class PathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    edge_limit: Optional[int] = Field(default=50, alias="edgeLimit")
    end_point: Optional[str] = Field(default=None, alias="endPoint")
    exclude_events: Optional[list[str]] = Field(default=None, alias="excludeEvents")
    include_event_types: Optional[list[PathType]] = Field(default=None, alias="includeEventTypes")
    local_path_cleaning_filters: Optional[list[PathCleaningFilter]] = Field(
        default=None, alias="localPathCleaningFilters"
    )
    max_edge_weight: Optional[int] = Field(default=None, alias="maxEdgeWeight")
    min_edge_weight: Optional[int] = Field(default=None, alias="minEdgeWeight")
    path_dropoff_key: Optional[str] = Field(
        default=None, alias="pathDropoffKey", description="Relevant only within actors query"
    )
    path_end_key: Optional[str] = Field(
        default=None, alias="pathEndKey", description="Relevant only within actors query"
    )
    path_groupings: Optional[list[str]] = Field(default=None, alias="pathGroupings")
    path_replacements: Optional[bool] = Field(default=None, alias="pathReplacements")
    path_start_key: Optional[str] = Field(
        default=None, alias="pathStartKey", description="Relevant only within actors query"
    )
    paths_hog_ql_expression: Optional[str] = Field(default=None, alias="pathsHogQLExpression")
    start_point: Optional[str] = Field(default=None, alias="startPoint")
    step_limit: Optional[int] = Field(default=5, alias="stepLimit")


class PathsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    edge_limit: Optional[int] = None
    end_point: Optional[str] = None
    exclude_events: Optional[list[str]] = None
    funnel_filter: Optional[dict[str, Any]] = None
    funnel_paths: Optional[FunnelPathType] = None
    include_event_types: Optional[list[PathType]] = None
    local_path_cleaning_filters: Optional[list[PathCleaningFilter]] = None
    max_edge_weight: Optional[int] = None
    min_edge_weight: Optional[int] = None
    path_groupings: Optional[list[str]] = None
    path_replacements: Optional[bool] = None
    path_type: Optional[PathType] = None
    paths_hogql_expression: Optional[str] = None
    start_point: Optional[str] = None
    step_limit: Optional[int] = None


class PropertyFilterType(str, Enum):
    META = "meta"
    EVENT = "event"
    PERSON = "person"
    ELEMENT = "element"
    FEATURE = "feature"
    SESSION = "session"
    COHORT = "cohort"
    RECORDING = "recording"
    GROUP = "group"
    HOGQL = "hogql"
    DATA_WAREHOUSE = "data_warehouse"
    DATA_WAREHOUSE_PERSON_PROPERTY = "data_warehouse_person_property"


class PropertyMathType(str, Enum):
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    P90 = "p90"
    P95 = "p95"
    P99 = "p99"


class PropertyOperator(str, Enum):
    EXACT = "exact"
    IS_NOT = "is_not"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"
    REGEX = "regex"
    NOT_REGEX = "not_regex"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"
    IS_DATE_EXACT = "is_date_exact"
    IS_DATE_BEFORE = "is_date_before"
    IS_DATE_AFTER = "is_date_after"
    BETWEEN = "between"
    NOT_BETWEEN = "not_between"
    MIN = "min"
    MAX = "max"


class QueryResponseAlternative1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: list[dict[str, Any]]


class QueryResponseAlternative4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[list[BreakdownItem]] = None
    compare: Optional[list[CompareItem]] = None
    day: Optional[list[DayItem]] = None
    interval: Optional[list[IntervalItem]] = None
    series: Optional[list[Series]] = None
    status: Optional[list[StatusItem]] = None


class QueryResponseAlternative6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: Optional[list] = None
    results: Any
    stdout: Optional[str] = None


class QueryResponseAlternative8(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    errors: list[HogQLNotice]
    input_expr: Optional[str] = Field(default=None, alias="inputExpr")
    input_select: Optional[str] = Field(default=None, alias="inputSelect")
    is_valid: Optional[bool] = Field(default=None, alias="isValid")
    is_valid_view: Optional[bool] = Field(default=None, alias="isValidView")
    notices: list[HogQLNotice]
    warnings: list[HogQLNotice]


class QueryResponseAlternative16(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: list[dict[str, Any]]


class QueryStatus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    complete: Optional[bool] = False
    end_time: Optional[AwareDatetime] = None
    error: Optional[bool] = False
    error_message: Optional[str] = None
    expiration_time: Optional[AwareDatetime] = None
    id: str
    query_async: Literal[True] = Field(default=True, description="ONLY async queries use QueryStatus.")
    query_progress: Optional[ClickhouseQueryProgress] = None
    results: Optional[Any] = None
    start_time: Optional[AwareDatetime] = None
    task_id: Optional[str] = None
    team_id: int


class QueryStatusResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    query_status: QueryStatus


class QueryTiming(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    k: str = Field(..., description="Key. Shortened to 'k' to save on data.")
    t: float = Field(..., description="Time in seconds. Shortened to 't' to save on data.")


class RecordingPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Union[DurationType, str]
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class Kind1(str, Enum):
    ACTIONS_NODE = "ActionsNode"
    EVENTS_NODE = "EventsNode"


class RetentionEntity(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    id: Optional[Union[str, float]] = None
    kind: Optional[Kind1] = None
    name: Optional[str] = None
    order: Optional[int] = None
    type: Optional[EntityType] = None
    uuid: Optional[str] = None


class RetentionReference(str, Enum):
    TOTAL = "total"
    PREVIOUS = "previous"


class RetentionPeriod(str, Enum):
    HOUR = "Hour"
    DAY = "Day"
    WEEK = "Week"
    MONTH = "Month"


class RetentionType(str, Enum):
    RETENTION_RECURRING = "retention_recurring"
    RETENTION_FIRST_TIME = "retention_first_time"


class RetentionValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: int


class SamplingRate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator: Optional[float] = None
    numerator: float


class SessionPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["session"] = "session"
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class StepOrderValue(str, Enum):
    STRICT = "strict"
    UNORDERED = "unordered"
    ORDERED = "ordered"


class StickinessFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[bool] = False
    display: Optional[ChartDisplayType] = None
    hidden_legend_indexes: Optional[list[float]] = None
    show_legend: Optional[bool] = Field(default=None, alias="showLegend")
    show_values_on_series: Optional[bool] = Field(default=None, alias="showValuesOnSeries")


class StickinessFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[bool] = None
    display: Optional[ChartDisplayType] = None
    hidden_legend_indexes: Optional[list[float]] = None
    show_legend: Optional[bool] = None
    show_values_on_series: Optional[bool] = None


class StickinessQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TestBasicQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TestCachedBasicQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TimeToSeeDataQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["TimeToSeeDataQuery"] = "TimeToSeeDataQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[dict[str, Any]] = None
    session_end: Optional[str] = Field(default=None, alias="sessionEnd")
    session_id: Optional[str] = Field(
        default=None, alias="sessionId", description="Project to filter on. Defaults to current session"
    )
    session_start: Optional[str] = Field(
        default=None, alias="sessionStart", description="Session start time. Defaults to current time - 2 hours"
    )
    team_id: Optional[int] = Field(
        default=None, alias="teamId", description="Project to filter on. Defaults to current project"
    )


class TimeToSeeDataSessionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: list[dict[str, Any]]


class TimeToSeeDataWaterfallNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["TimeToSeeDataSessionsWaterfallNode"] = "TimeToSeeDataSessionsWaterfallNode"
    source: TimeToSeeDataQuery


class TimelineEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[EventType]
    recording_duration_s: Optional[float] = Field(default=None, description="Duration of the recording in seconds.")
    session_id: Optional[str] = Field(
        default=None, alias="sessionId", description="Session ID. None means out-of-session events"
    )


class TrendsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_axis_format: Optional[AggregationAxisFormat] = Field(
        default=AggregationAxisFormat.NUMERIC, alias="aggregationAxisFormat"
    )
    aggregation_axis_postfix: Optional[str] = Field(default=None, alias="aggregationAxisPostfix")
    aggregation_axis_prefix: Optional[str] = Field(default=None, alias="aggregationAxisPrefix")
    breakdown_histogram_bin_count: Optional[float] = None
    compare: Optional[bool] = False
    decimal_places: Optional[float] = Field(default=None, alias="decimalPlaces")
    display: Optional[ChartDisplayType] = ChartDisplayType.ACTIONS_LINE_GRAPH
    formula: Optional[str] = None
    hidden_legend_indexes: Optional[list[float]] = None
    show_labels_on_series: Optional[bool] = Field(default=None, alias="showLabelsOnSeries")
    show_legend: Optional[bool] = Field(default=False, alias="showLegend")
    show_percent_stack_view: Optional[bool] = Field(default=False, alias="showPercentStackView")
    show_values_on_series: Optional[bool] = Field(default=False, alias="showValuesOnSeries")
    smoothing_intervals: Optional[int] = Field(default=1, alias="smoothingIntervals")


class TrendsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_axis_format: Optional[AggregationAxisFormat] = None
    aggregation_axis_postfix: Optional[str] = None
    aggregation_axis_prefix: Optional[str] = None
    breakdown_histogram_bin_count: Optional[float] = None
    compare: Optional[bool] = None
    decimal_places: Optional[float] = None
    display: Optional[ChartDisplayType] = None
    formula: Optional[str] = None
    hidden_legend_indexes: Optional[list[float]] = None
    show_labels_on_series: Optional[bool] = None
    show_legend: Optional[bool] = None
    show_percent_stack_view: Optional[bool] = None
    show_values_on_series: Optional[bool] = None
    smoothing_intervals: Optional[float] = None


class TrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ActionsPie(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    disable_hover_offset: Optional[bool] = Field(default=None, alias="disableHoverOffset")
    hide_aggregation: Optional[bool] = Field(default=None, alias="hideAggregation")


class Retention(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hide_line_graph: Optional[bool] = Field(default=None, alias="hideLineGraph")
    hide_size_column: Optional[bool] = Field(default=None, alias="hideSizeColumn")
    use_small_layout: Optional[bool] = Field(default=None, alias="useSmallLayout")


class VizSpecificOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions_pie: Optional[ActionsPie] = Field(default=None, alias="ActionsPie")
    retention: Optional[Retention] = Field(default=None, alias="RETENTION")


class Kind2(str, Enum):
    UNIT = "unit"
    DURATION_S = "duration_s"
    PERCENTAGE = "percentage"


class WebOverviewItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    change_from_previous_pct: Optional[float] = Field(default=None, alias="changeFromPreviousPct")
    is_increase_bad: Optional[bool] = Field(default=None, alias="isIncreaseBad")
    key: str
    kind: Kind2
    previous: Optional[float] = None
    value: Optional[float] = None


class Sampling(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    enabled: Optional[bool] = None
    force_sampling_rate: Optional[SamplingRate] = Field(default=None, alias="forceSamplingRate")


class WebOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = Field(default=None, alias="dateFrom")
    date_to: Optional[str] = Field(default=None, alias="dateTo")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[WebOverviewItem]
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebStatsBreakdown(str, Enum):
    PAGE = "Page"
    INITIAL_PAGE = "InitialPage"
    EXIT_PAGE = "ExitPage"
    INITIAL_CHANNEL_TYPE = "InitialChannelType"
    INITIAL_REFERRING_DOMAIN = "InitialReferringDomain"
    INITIAL_UTM_SOURCE = "InitialUTMSource"
    INITIAL_UTM_CAMPAIGN = "InitialUTMCampaign"
    INITIAL_UTM_MEDIUM = "InitialUTMMedium"
    INITIAL_UTM_TERM = "InitialUTMTerm"
    INITIAL_UTM_CONTENT = "InitialUTMContent"
    BROWSER = "Browser"
    OS = "OS"
    DEVICE_TYPE = "DeviceType"
    COUNTRY = "Country"
    REGION = "Region"
    CITY = "City"


class WebStatsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class WebTopClicksQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class ActorsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class Breakdown(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    normalize_url: Optional[bool] = None
    property: Union[str, float]
    type: BreakdownType


class BreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[Union[str, float, list[Union[str, float]]]] = None
    breakdown_group_type_index: Optional[int] = None
    breakdown_hide_other_aggregation: Optional[bool] = None
    breakdown_histogram_bin_count: Optional[int] = None
    breakdown_limit: Optional[int] = None
    breakdown_normalize_url: Optional[bool] = None
    breakdown_type: Optional[BreakdownType] = BreakdownType.EVENT
    breakdowns: Optional[list[Breakdown]] = None


class CacheMissResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: Optional[str] = None
    query_status: Optional[QueryStatus] = None


class CachedActorsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedFunnelCorrelationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: FunnelCorrelationResult
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: Union[FunnelTimeToConvertResults, list[dict[str, Any]], list[list[dict[str, Any]]]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedInsightActorsQueryOptionsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[list[BreakdownItem]] = None
    cache_key: str
    compare: Optional[list[CompareItem]] = None
    day: Optional[list[DayItem]] = None
    interval: Optional[list[IntervalItem]] = None
    is_cached: bool
    last_refresh: AwareDatetime
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    series: Optional[list[Series]] = None
    status: Optional[list[StatusItem]] = None
    timezone: str


class CachedLifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedPathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedSessionsTimelineQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[TimelineEntry]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedStickinessQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    date_from: Optional[str] = Field(default=None, alias="dateFrom")
    date_to: Optional[str] = Field(default=None, alias="dateTo")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[WebOverviewItem]
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebStatsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedWebTopClicksQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class Response(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class Response1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class Response4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = Field(default=None, alias="dateFrom")
    date_to: Optional[str] = Field(default=None, alias="dateTo")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[WebOverviewItem]
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class Response6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class ChartSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    goal_lines: Optional[list[GoalLine]] = Field(default=None, alias="goalLines")
    x_axis: Optional[ChartAxis] = Field(default=None, alias="xAxis")
    y_axis: Optional[list[ChartAxis]] = Field(default=None, alias="yAxis")


class DataWarehousePersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["data_warehouse_person_property"] = "data_warehouse_person_property"
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class DataWarehousePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["data_warehouse"] = "data_warehouse"
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class DatabaseSchemaField(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chain: Optional[list[Union[str, int]]] = None
    fields: Optional[list[str]] = None
    hogql_value: str
    name: str
    schema_valid: bool
    table: Optional[str] = None
    type: DatabaseSerializedFieldType


class DatabaseSchemaPostHogTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    type: Literal["posthog"] = "posthog"


class DatabaseSchemaTableCommon(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    type: Type


class ElementPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Key
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["element"] = "element"
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class EventPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: Optional[PropertyOperator] = PropertyOperator.EXACT
    type: Literal["event"] = Field(default="event", description="Event properties")
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class EventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class FeaturePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["feature"] = Field(default="feature", description='Event property with "$feature/" prepended')
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class FunnelCorrelationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: FunnelCorrelationResult
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class FunnelsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bin_count: Optional[Union[float, str]] = None
    breakdown_attribution_type: Optional[BreakdownAttributionType] = None
    breakdown_attribution_value: Optional[float] = None
    exclusions: Optional[list[FunnelExclusionLegacy]] = None
    funnel_aggregate_by_hogql: Optional[str] = None
    funnel_from_step: Optional[float] = None
    funnel_order_type: Optional[StepOrderValue] = None
    funnel_step_reference: Optional[FunnelStepReference] = None
    funnel_to_step: Optional[float] = None
    funnel_viz_type: Optional[FunnelVizType] = None
    funnel_window_interval: Optional[float] = None
    funnel_window_interval_unit: Optional[FunnelConversionWindowTimeUnit] = None
    hidden_legend_breakdowns: Optional[list[str]] = None
    layout: Optional[FunnelLayout] = None


class FunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: Union[FunnelTimeToConvertResults, list[dict[str, Any]], list[list[dict[str, Any]]]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class GenericCachedQueryResponse(BaseModel):
    cache_key: str
    is_cached: bool
    last_refresh: AwareDatetime
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timezone: str


class GroupPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: Optional[float] = None
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["group"] = "group"
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class HogQLAutocompleteResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incomplete_list: bool = Field(..., description="Whether or not the suggestions returned are complete")
    suggestions: list[AutocompleteCompletionItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class HogQLMetadataResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    errors: list[HogQLNotice]
    input_expr: Optional[str] = Field(default=None, alias="inputExpr")
    input_select: Optional[str] = Field(default=None, alias="inputSelect")
    is_valid: Optional[bool] = Field(default=None, alias="isValid")
    is_valid_view: Optional[bool] = Field(default=None, alias="isValidView")
    notices: list[HogQLNotice]
    warnings: list[HogQLNotice]


class HogQLPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    type: Literal["hogql"] = "hogql"
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class HogQLQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class HogQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Optional[str] = None
    kind: Literal["HogQuery"] = "HogQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[HogQueryResponse] = None


class InsightActorsQueryBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    include_recordings: Optional[bool] = Field(default=None, alias="includeRecordings")
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None


class LifecycleFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    show_legend: Optional[bool] = Field(default=False, alias="showLegend")
    show_values_on_series: Optional[bool] = Field(default=None, alias="showValuesOnSeries")
    toggled_lifecycles: Optional[list[LifecycleToggle]] = Field(default=None, alias="toggledLifecycles")


class LifecycleFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    show_legend: Optional[bool] = None
    show_values_on_series: Optional[bool] = None
    toggled_lifecycles: Optional[list[LifecycleToggle]] = Field(default=None, alias="toggledLifecycles")


class LifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class PathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class PersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["person"] = Field(default="person", description="Person properties")
    value: Optional[Union[str, float, list[Union[str, float]]]] = None


class QueryResponseAlternative2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[TimelineEntry]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative7(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class QueryResponseAlternative9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incomplete_list: bool = Field(..., description="Whether or not the suggestions returned are complete")
    suggestions: list[AutocompleteCompletionItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative10(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = Field(default=None, alias="dateFrom")
    date_to: Optional[str] = Field(default=None, alias="dateTo")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[WebOverviewItem]
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative11(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative12(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative13(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative14(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative15(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class QueryResponseAlternative17(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = Field(default=None, alias="dateFrom")
    date_to: Optional[str] = Field(default=None, alias="dateTo")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[WebOverviewItem]
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative18(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative19(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list
    sampling_rate: Optional[SamplingRate] = Field(default=None, alias="samplingRate")
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative20(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative21(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: Union[FunnelTimeToConvertResults, list[dict[str, Any]], list[list[dict[str, Any]]]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative23(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative26(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    results: FunnelCorrelationResult
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class RetentionFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    period: Optional[RetentionPeriod] = RetentionPeriod.DAY
    retention_reference: Optional[RetentionReference] = Field(default=None, alias="retentionReference")
    retention_type: Optional[RetentionType] = Field(default=None, alias="retentionType")
    returning_entity: Optional[RetentionEntity] = Field(default=None, alias="returningEntity")
    show_mean: Optional[bool] = Field(default=None, alias="showMean")
    target_entity: Optional[RetentionEntity] = Field(default=None, alias="targetEntity")
    total_intervals: Optional[int] = Field(default=11, alias="totalIntervals")


class RetentionFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    period: Optional[RetentionPeriod] = None
    retention_reference: Optional[RetentionReference] = None
    retention_type: Optional[RetentionType] = None
    returning_entity: Optional[RetentionEntity] = None
    show_mean: Optional[bool] = None
    target_entity: Optional[RetentionEntity] = None
    total_intervals: Optional[int] = None


class RetentionResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date: AwareDatetime
    label: str
    values: list[RetentionValue]


class SavedInsightNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    allow_sorting: Optional[bool] = Field(
        default=None,
        alias="allowSorting",
        description="Can the user click on column headers to sort the table? (default: true)",
    )
    embedded: Optional[bool] = Field(default=None, description="Query is embedded inside another bordered component")
    expandable: Optional[bool] = Field(
        default=None, description="Can expand row to show raw event data (default: true)"
    )
    full: Optional[bool] = Field(
        default=None, description="Show with most visual options enabled. Used in insight scene."
    )
    hide_persons_modal: Optional[bool] = Field(default=None, alias="hidePersonsModal")
    kind: Literal["SavedInsightNode"] = "SavedInsightNode"
    properties_via_url: Optional[bool] = Field(
        default=None, alias="propertiesViaUrl", description="Link properties via the URL (default: false)"
    )
    short_id: str = Field(..., alias="shortId")
    show_actions: Optional[bool] = Field(
        default=None, alias="showActions", description="Show the kebab menu at the end of the row"
    )
    show_column_configurator: Optional[bool] = Field(
        default=None,
        alias="showColumnConfigurator",
        description="Show a button to configure the table's columns if possible",
    )
    show_correlation_table: Optional[bool] = Field(default=None, alias="showCorrelationTable")
    show_date_range: Optional[bool] = Field(default=None, alias="showDateRange", description="Show date range selector")
    show_elapsed_time: Optional[bool] = Field(
        default=None, alias="showElapsedTime", description="Show the time it takes to run a query"
    )
    show_event_filter: Optional[bool] = Field(
        default=None, alias="showEventFilter", description="Include an event filter above the table (EventsNode only)"
    )
    show_export: Optional[bool] = Field(default=None, alias="showExport", description="Show the export button")
    show_filters: Optional[bool] = Field(default=None, alias="showFilters")
    show_header: Optional[bool] = Field(default=None, alias="showHeader")
    show_hog_ql_editor: Optional[bool] = Field(
        default=None, alias="showHogQLEditor", description="Include a HogQL query editor above HogQL tables"
    )
    show_last_computation: Optional[bool] = Field(default=None, alias="showLastComputation")
    show_last_computation_refresh: Optional[bool] = Field(default=None, alias="showLastComputationRefresh")
    show_open_editor_button: Optional[bool] = Field(
        default=None,
        alias="showOpenEditorButton",
        description="Show a button to open the current query as a new insight. (default: true)",
    )
    show_persistent_column_configurator: Optional[bool] = Field(
        default=None,
        alias="showPersistentColumnConfigurator",
        description="Show a button to configure and persist the table's default columns if possible",
    )
    show_property_filter: Optional[bool] = Field(
        default=None, alias="showPropertyFilter", description="Include a property filter above the table"
    )
    show_reload: Optional[bool] = Field(default=None, alias="showReload", description="Show a reload button")
    show_results: Optional[bool] = Field(default=None, alias="showResults")
    show_results_table: Optional[bool] = Field(
        default=None, alias="showResultsTable", description="Show a results table"
    )
    show_saved_queries: Optional[bool] = Field(
        default=None, alias="showSavedQueries", description="Shows a list of saved queries"
    )
    show_search: Optional[bool] = Field(
        default=None, alias="showSearch", description="Include a free text search field (PersonsNode only)"
    )
    show_table: Optional[bool] = Field(default=None, alias="showTable")
    show_test_account_filters: Optional[bool] = Field(
        default=None, alias="showTestAccountFilters", description="Show filter to exclude test accounts"
    )
    show_timings: Optional[bool] = Field(
        default=None, alias="showTimings", description="Show a detailed query timing breakdown"
    )
    suppress_session_analysis_warning: Optional[bool] = Field(default=None, alias="suppressSessionAnalysisWarning")
    viz_specific_options: Optional[VizSpecificOptions] = Field(default=None, alias="vizSpecificOptions")


class SessionsTimelineQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[TimelineEntry]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TimeToSeeDataJSONNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["TimeToSeeDataSessionsJSONNode"] = "TimeToSeeDataSessionsJSONNode"
    source: TimeToSeeDataQuery


class TimeToSeeDataNode(RootModel[Union[TimeToSeeDataJSONNode, TimeToSeeDataWaterfallNode]]):
    root: Union[TimeToSeeDataJSONNode, TimeToSeeDataWaterfallNode]


class TimeToSeeDataSessionsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: Optional[DateRange] = Field(default=None, alias="dateRange", description="Date range for the query")
    kind: Literal["TimeToSeeDataSessionsQuery"] = "TimeToSeeDataSessionsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[TimeToSeeDataSessionsQueryResponse] = None
    team_id: Optional[int] = Field(
        default=None, alias="teamId", description="Project to filter on. Defaults to current project"
    )


class WebOverviewQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[bool] = None
    date_range: Optional[DateRange] = Field(default=None, alias="dateRange")
    kind: Literal["WebOverviewQuery"] = "WebOverviewQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebOverviewQueryResponse] = None
    sampling: Optional[Sampling] = None
    use_sessions_table: Optional[bool] = Field(default=None, alias="useSessionsTable")


class WebStatsTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_by: WebStatsBreakdown = Field(..., alias="breakdownBy")
    date_range: Optional[DateRange] = Field(default=None, alias="dateRange")
    do_path_cleaning: Optional[bool] = Field(default=None, alias="doPathCleaning")
    include_bounce_rate: Optional[bool] = Field(default=None, alias="includeBounceRate")
    include_scroll_depth: Optional[bool] = Field(default=None, alias="includeScrollDepth")
    kind: Literal["WebStatsTableQuery"] = "WebStatsTableQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebStatsTableQueryResponse] = None
    sampling: Optional[Sampling] = None
    use_sessions_table: Optional[bool] = Field(default=None, alias="useSessionsTable")


class WebTopClicksQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: Optional[DateRange] = Field(default=None, alias="dateRange")
    kind: Literal["WebTopClicksQuery"] = "WebTopClicksQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebTopClicksQueryResponse] = None
    sampling: Optional[Sampling] = None
    use_sessions_table: Optional[bool] = Field(default=None, alias="useSessionsTable")


class AnyResponseType(
    RootModel[
        Union[
            dict[str, Any],
            HogQueryResponse,
            HogQLQueryResponse,
            HogQLMetadataResponse,
            HogQLAutocompleteResponse,
            Any,
            EventsQueryResponse,
        ]
    ]
):
    root: Union[
        dict[str, Any],
        HogQueryResponse,
        HogQLQueryResponse,
        HogQLMetadataResponse,
        HogQLAutocompleteResponse,
        Any,
        EventsQueryResponse,
    ]


class CachedHogQLQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class CachedRetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: AwareDatetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: AwareDatetime
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    results: list[RetentionResult]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class DashboardFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = None


class Response2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: Optional[str] = Field(default=None, description="Executed ClickHouse query")
    columns: Optional[list] = Field(default=None, description="Returned columns")
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: Optional[list[str]] = Field(default=None, description="Query explanation output")
    has_more: Optional[bool] = Field(default=None, alias="hasMore")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class DataWarehouseNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    distinct_id_field: str
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
    math: Optional[
        Union[BaseMathType, PropertyMathType, CountPerActorMathType, Literal["unique_group"], Literal["hogql"]]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_property: Optional[str] = None
    name: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    table_name: str
    timestamp_field: str


class DatabaseSchemaDataWarehouseTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    format: str
    id: str
    name: str
    schema_: Optional[DatabaseSchemaSchema] = Field(default=None, alias="schema")
    source: Optional[DatabaseSchemaSource] = None
    type: Literal["data_warehouse"] = "data_warehouse"
    url_pattern: str


class EntityNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: NodeKind
    math: Optional[
        Union[BaseMathType, PropertyMathType, CountPerActorMathType, Literal["unique_group"], Literal["hogql"]]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_property: Optional[str] = None
    name: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None


class EventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    event: Optional[str] = Field(default=None, description="The event or `null` for all events.")
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsNode"] = "EventsNode"
    limit: Optional[int] = None
    math: Optional[
        Union[BaseMathType, PropertyMathType, CountPerActorMathType, Literal["unique_group"], Literal["hogql"]]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_property: Optional[str] = None
    name: Optional[str] = None
    order_by: Optional[list[str]] = Field(default=None, alias="orderBy", description="Columns to order by")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None


class EventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    action_id: Optional[int] = Field(default=None, alias="actionId", description="Show events matching a given action")
    after: Optional[str] = Field(default=None, description="Only fetch events that happened after this timestamp")
    before: Optional[str] = Field(default=None, description="Only fetch events that happened before this timestamp")
    event: Optional[str] = Field(default=None, description="Limit to events matching this string")
    filter_test_accounts: Optional[bool] = Field(
        default=None, alias="filterTestAccounts", description="Filter test accounts"
    )
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsQuery"] = "EventsQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    order_by: Optional[list[str]] = Field(default=None, alias="orderBy", description="Columns to order by")
    person_id: Optional[str] = Field(default=None, alias="personId", description="Show events for a given person")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[EventsQueryResponse] = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    where: Optional[list[str]] = Field(default=None, description="HogQL filters to apply on returned data")


class FunnelExclusionActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    funnel_from_step: int = Field(..., alias="funnelFromStep")
    funnel_to_step: int = Field(..., alias="funnelToStep")
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[
        Union[BaseMathType, PropertyMathType, CountPerActorMathType, Literal["unique_group"], Literal["hogql"]]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_property: Optional[str] = None
    name: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None


class FunnelExclusionEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    event: Optional[str] = Field(default=None, description="The event or `null` for all events.")
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    funnel_from_step: int = Field(..., alias="funnelFromStep")
    funnel_to_step: int = Field(..., alias="funnelToStep")
    kind: Literal["EventsNode"] = "EventsNode"
    limit: Optional[int] = None
    math: Optional[
        Union[BaseMathType, PropertyMathType, CountPerActorMathType, Literal["unique_group"], Literal["hogql"]]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_property: Optional[str] = None
    name: Optional[str] = None
    order_by: Optional[list[str]] = Field(default=None, alias="orderBy", description="Columns to order by")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None


class HogQLFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: Optional[DateRange] = Field(default=None, alias="dateRange")
    filter_test_accounts: Optional[bool] = Field(default=None, alias="filterTestAccounts")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = None


class HogQLQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    explain: Optional[bool] = None
    filters: Optional[HogQLFilters] = None
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query: str
    response: Optional[HogQLQueryResponse] = None
    values: Optional[dict[str, Any]] = Field(
        default=None, description="Constant values that can be referenced with the {placeholder} syntax in the query"
    )


class PersonsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cohort: Optional[int] = None
    distinct_id: Optional[str] = Field(default=None, alias="distinctId")
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["PersonsNode"] = "PersonsNode"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    search: Optional[str] = None


class PropertyGroupFilterValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[
        Union[
            PropertyGroupFilterValue,
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ],
        ]
    ]


class QueryResponseAlternative22(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[RetentionResult]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    results: list[RetentionResult]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class SessionsTimelineQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after: Optional[str] = Field(
        default=None, description="Only fetch sessions that started after this timestamp (default: '-24h')"
    )
    before: Optional[str] = Field(
        default=None, description="Only fetch sessions that started before this timestamp (default: '+5s')"
    )
    kind: Literal["SessionsTimelineQuery"] = "SessionsTimelineQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    person_id: Optional[str] = Field(
        default=None, alias="personId", description="Fetch sessions only for a given person"
    )
    response: Optional[SessionsTimelineQueryResponse] = None


class ActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    fixed_properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[
        Union[BaseMathType, PropertyMathType, CountPerActorMathType, Literal["unique_group"], Literal["hogql"]]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_property: Optional[str] = None
    name: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None


class DataVisualizationNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chart_settings: Optional[ChartSettings] = Field(default=None, alias="chartSettings")
    display: Optional[ChartDisplayType] = None
    kind: Literal["DataVisualizationNode"] = "DataVisualizationNode"
    source: HogQLQuery


class DatabaseSchemaViewTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    query: HogQLQuery
    type: Literal["view"] = "view"


class FunnelsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bin_count: Optional[int] = Field(default=None, alias="binCount")
    breakdown_attribution_type: Optional[BreakdownAttributionType] = Field(
        default=BreakdownAttributionType.FIRST_TOUCH, alias="breakdownAttributionType"
    )
    breakdown_attribution_value: Optional[int] = Field(default=None, alias="breakdownAttributionValue")
    exclusions: Optional[list[Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]]] = []
    funnel_aggregate_by_hog_ql: Optional[str] = Field(default=None, alias="funnelAggregateByHogQL")
    funnel_from_step: Optional[int] = Field(default=None, alias="funnelFromStep")
    funnel_order_type: Optional[StepOrderValue] = Field(default=StepOrderValue.ORDERED, alias="funnelOrderType")
    funnel_step_reference: Optional[FunnelStepReference] = Field(
        default=FunnelStepReference.TOTAL, alias="funnelStepReference"
    )
    funnel_to_step: Optional[int] = Field(default=None, alias="funnelToStep")
    funnel_viz_type: Optional[FunnelVizType] = Field(default=FunnelVizType.STEPS, alias="funnelVizType")
    funnel_window_interval: Optional[int] = Field(default=14, alias="funnelWindowInterval")
    funnel_window_interval_unit: Optional[FunnelConversionWindowTimeUnit] = Field(
        default=FunnelConversionWindowTimeUnit.DAY, alias="funnelWindowIntervalUnit"
    )
    hidden_legend_breakdowns: Optional[list[str]] = None
    layout: Optional[FunnelLayout] = FunnelLayout.VERTICAL


class HasPropertiesNode(RootModel[Union[EventsNode, EventsQuery, PersonsNode]]):
    root: Union[EventsNode, EventsQuery, PersonsNode]


class HogQLAutocomplete(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    end_position: int = Field(..., alias="endPosition", description="End position of the editor word")
    filters: Optional[HogQLFilters] = Field(default=None, description="Table to validate the expression against")
    kind: Literal["HogQLAutocomplete"] = "HogQLAutocomplete"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[HogQLAutocompleteResponse] = None
    select: str = Field(..., description="Full select query to validate")
    start_position: int = Field(..., alias="startPosition", description="Start position of the editor word")


class InsightFilter(
    RootModel[Union[TrendsFilter, FunnelsFilter, RetentionFilter, PathsFilter, StickinessFilter, LifecycleFilter]]
):
    root: Union[TrendsFilter, FunnelsFilter, RetentionFilter, PathsFilter, StickinessFilter, LifecycleFilter]


class PropertyGroupFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[PropertyGroupFilterValue]


class RetentionQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    kind: Literal["RetentionQuery"] = "RetentionQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[RetentionQueryResponse] = None
    retention_filter: RetentionFilter = Field(
        ..., alias="retentionFilter", description="Properties specific to the retention insight"
    )
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")


class StickinessQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["StickinessQuery"] = "StickinessQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[StickinessQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    stickiness_filter: Optional[StickinessFilter] = Field(
        default=None, alias="stickinessFilter", description="Properties specific to the stickiness insight"
    )


class TrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdown_filter: Optional[BreakdownFilter] = Field(
        default=None, alias="breakdownFilter", description="Breakdown of the events and actions"
    )
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["TrendsQuery"] = "TrendsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[TrendsQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    trends_filter: Optional[TrendsFilter] = Field(
        default=None, alias="trendsFilter", description="Properties specific to the trends insight"
    )


class FilterType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions: Optional[list[dict[str, Any]]] = None
    aggregation_group_type_index: Optional[float] = None
    breakdown: Optional[Union[str, float, list[Union[str, float]]]] = None
    breakdown_group_type_index: Optional[float] = None
    breakdown_hide_other_aggregation: Optional[bool] = None
    breakdown_limit: Optional[int] = None
    breakdown_normalize_url: Optional[bool] = None
    breakdown_type: Optional[BreakdownType] = None
    breakdowns: Optional[list[Breakdown]] = None
    data_warehouse: Optional[list[dict[str, Any]]] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    entity_id: Optional[Union[str, float]] = None
    entity_math: Optional[str] = None
    entity_type: Optional[EntityType] = None
    events: Optional[list[dict[str, Any]]] = None
    explicit_date: Optional[Union[bool, str]] = Field(
        default=None,
        description=(
            "Whether the `date_from` and `date_to` should be used verbatim. Disables rounding to the start and end of"
            ' period. Strings are cast to bools, e.g. "true" -> true.'
        ),
    )
    filter_test_accounts: Optional[bool] = None
    from_dashboard: Optional[Union[bool, float]] = None
    insight: Optional[InsightType] = None
    interval: Optional[IntervalType] = None
    new_entity: Optional[list[dict[str, Any]]] = None
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = None
    sampling_factor: Optional[float] = None


class FunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdown_filter: Optional[BreakdownFilter] = Field(
        default=None, alias="breakdownFilter", description="Breakdown of the events and actions"
    )
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    funnels_filter: Optional[FunnelsFilter] = Field(
        default=None, alias="funnelsFilter", description="Properties specific to the funnels insight"
    )
    interval: Optional[IntervalType] = Field(
        default=None, description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`"
    )
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[FunnelsQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )


class InsightsQueryBaseFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[FunnelsQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")


class InsightsQueryBaseLifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[LifecycleQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")


class InsightsQueryBasePathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[PathsQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")


class InsightsQueryBaseRetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[RetentionQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")


class InsightsQueryBaseTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[TrendsQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")


class LifecycleQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["LifecycleQuery"] = "LifecycleQuery"
    lifecycle_filter: Optional[LifecycleFilter] = Field(
        default=None, alias="lifecycleFilter", description="Properties specific to the lifecycle insight"
    )
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[LifecycleQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )


class NamedParametersTypeofDateRangeForFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    source: Optional[FilterType] = None


class QueryResponseAlternative27(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    tables: dict[str, Union[DatabaseSchemaPostHogTable, DatabaseSchemaDataWarehouseTable, DatabaseSchemaViewTable]]


class QueryResponseAlternative(
    RootModel[
        Union[
            dict[str, Any],
            QueryResponseAlternative1,
            QueryResponseAlternative2,
            QueryResponseAlternative3,
            QueryResponseAlternative4,
            QueryResponseAlternative5,
            QueryResponseAlternative6,
            QueryResponseAlternative7,
            QueryResponseAlternative8,
            QueryResponseAlternative9,
            QueryResponseAlternative10,
            QueryResponseAlternative11,
            QueryResponseAlternative12,
            Any,
            QueryResponseAlternative13,
            QueryResponseAlternative14,
            QueryResponseAlternative15,
            QueryResponseAlternative16,
            QueryResponseAlternative17,
            QueryResponseAlternative18,
            QueryResponseAlternative19,
            QueryResponseAlternative20,
            QueryResponseAlternative21,
            QueryResponseAlternative22,
            QueryResponseAlternative23,
            QueryResponseAlternative26,
            QueryResponseAlternative27,
        ]
    ]
):
    root: Union[
        dict[str, Any],
        QueryResponseAlternative1,
        QueryResponseAlternative2,
        QueryResponseAlternative3,
        QueryResponseAlternative4,
        QueryResponseAlternative5,
        QueryResponseAlternative6,
        QueryResponseAlternative7,
        QueryResponseAlternative8,
        QueryResponseAlternative9,
        QueryResponseAlternative10,
        QueryResponseAlternative11,
        QueryResponseAlternative12,
        Any,
        QueryResponseAlternative13,
        QueryResponseAlternative14,
        QueryResponseAlternative15,
        QueryResponseAlternative16,
        QueryResponseAlternative17,
        QueryResponseAlternative18,
        QueryResponseAlternative19,
        QueryResponseAlternative20,
        QueryResponseAlternative21,
        QueryResponseAlternative22,
        QueryResponseAlternative23,
        QueryResponseAlternative26,
        QueryResponseAlternative27,
    ]


class DatabaseSchemaQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    tables: dict[str, Union[DatabaseSchemaPostHogTable, DatabaseSchemaDataWarehouseTable, DatabaseSchemaViewTable]]


class FunnelPathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_path_type: Optional[FunnelPathType] = Field(default=None, alias="funnelPathType")
    funnel_source: FunnelsQuery = Field(..., alias="funnelSource")
    funnel_step: Optional[int] = Field(default=None, alias="funnelStep")


class FunnelsActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_custom_steps: Optional[list[int]] = Field(
        default=None,
        alias="funnelCustomSteps",
        description=(
            "Custom step numbers to get persons for. This overrides `funnelStep`. Primarily for correlation use."
        ),
    )
    funnel_step: Optional[int] = Field(
        default=None,
        alias="funnelStep",
        description=(
            "Index of the step for which we want to get the timestamp for, per person. Positive for converted persons,"
            " negative for dropped of persons."
        ),
    )
    funnel_step_breakdown: Optional[Union[str, float, list[Union[str, float]]]] = Field(
        default=None,
        alias="funnelStepBreakdown",
        description=(
            "The breakdown value for which to get persons for. This is an array for person and event properties, a"
            " string for groups and an integer for cohorts."
        ),
    )
    funnel_trends_drop_off: Optional[bool] = Field(default=None, alias="funnelTrendsDropOff")
    funnel_trends_entrance_period_start: Optional[str] = Field(
        default=None,
        alias="funnelTrendsEntrancePeriodStart",
        description="Used together with `funnelTrendsDropOff` for funnels time conversion date for the persons modal.",
    )
    include_recordings: Optional[bool] = Field(default=None, alias="includeRecordings")
    kind: Literal["FunnelsActorsQuery"] = "FunnelsActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    source: FunnelsQuery


class PathsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    date_range: Optional[InsightDateRange] = Field(
        default=None, alias="dateRange", description="Date range for the query"
    )
    filter_test_accounts: Optional[bool] = Field(
        default=False,
        alias="filterTestAccounts",
        description="Exclude internal and test users by applying the respective filters",
    )
    funnel_paths_filter: Optional[FunnelPathsFilter] = Field(
        default=None, alias="funnelPathsFilter", description="Used for displaying paths in relation to funnel steps."
    )
    kind: Literal["PathsQuery"] = "PathsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    paths_filter: PathsFilter = Field(..., alias="pathsFilter", description="Properties specific to the paths insight")
    properties: Optional[
        Union[
            list[
                Union[
                    EventPropertyFilter,
                    PersonPropertyFilter,
                    ElementPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[PathsQueryResponse] = None
    sampling_factor: Optional[float] = Field(default=None, alias="samplingFactor", description="Sampling rate")


class DatabaseSchemaQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["DatabaseSchemaQuery"] = "DatabaseSchemaQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[DatabaseSchemaQueryResponse] = None


class FunnelCorrelationQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_correlation_event_exclude_property_names: Optional[list[str]] = Field(
        default=None, alias="funnelCorrelationEventExcludePropertyNames"
    )
    funnel_correlation_event_names: Optional[list[str]] = Field(default=None, alias="funnelCorrelationEventNames")
    funnel_correlation_exclude_event_names: Optional[list[str]] = Field(
        default=None, alias="funnelCorrelationExcludeEventNames"
    )
    funnel_correlation_exclude_names: Optional[list[str]] = Field(default=None, alias="funnelCorrelationExcludeNames")
    funnel_correlation_names: Optional[list[str]] = Field(default=None, alias="funnelCorrelationNames")
    funnel_correlation_type: FunnelCorrelationResultsType = Field(..., alias="funnelCorrelationType")
    kind: Literal["FunnelCorrelationQuery"] = "FunnelCorrelationQuery"
    response: Optional[FunnelCorrelationResponse] = None
    source: FunnelsActorsQuery


class InsightVizNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    embedded: Optional[bool] = Field(default=None, description="Query is embedded inside another bordered component")
    full: Optional[bool] = Field(
        default=None, description="Show with most visual options enabled. Used in insight scene."
    )
    hide_persons_modal: Optional[bool] = Field(default=None, alias="hidePersonsModal")
    kind: Literal["InsightVizNode"] = "InsightVizNode"
    show_correlation_table: Optional[bool] = Field(default=None, alias="showCorrelationTable")
    show_filters: Optional[bool] = Field(default=None, alias="showFilters")
    show_header: Optional[bool] = Field(default=None, alias="showHeader")
    show_last_computation: Optional[bool] = Field(default=None, alias="showLastComputation")
    show_last_computation_refresh: Optional[bool] = Field(default=None, alias="showLastComputationRefresh")
    show_results: Optional[bool] = Field(default=None, alias="showResults")
    show_table: Optional[bool] = Field(default=None, alias="showTable")
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    suppress_session_analysis_warning: Optional[bool] = Field(default=None, alias="suppressSessionAnalysisWarning")
    viz_specific_options: Optional[VizSpecificOptions] = Field(default=None, alias="vizSpecificOptions")


class FunnelCorrelationActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_correlation_person_converted: Optional[bool] = Field(default=None, alias="funnelCorrelationPersonConverted")
    funnel_correlation_person_entity: Optional[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        default=None, alias="funnelCorrelationPersonEntity"
    )
    funnel_correlation_property_values: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
            ]
        ]
    ] = Field(default=None, alias="funnelCorrelationPropertyValues")
    include_recordings: Optional[bool] = Field(default=None, alias="includeRecordings")
    kind: Literal["FunnelCorrelationActorsQuery"] = "FunnelCorrelationActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    source: FunnelCorrelationQuery


class InsightActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[Union[str, int]] = None
    compare: Optional[Compare] = None
    day: Optional[Union[str, int]] = None
    include_recordings: Optional[bool] = Field(default=None, alias="includeRecordings")
    interval: Optional[int] = Field(
        default=None, description="An interval selected out of available intervals in source query."
    )
    kind: Literal["InsightActorsQuery"] = "InsightActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    series: Optional[int] = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    status: Optional[str] = None


class InsightActorsQueryOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["InsightActorsQueryOptions"] = "InsightActorsQueryOptions"
    response: Optional[InsightActorsQueryOptionsResponse] = None
    source: Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery]


class ActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fixed_properties: Optional[
        list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]]
    ] = Field(
        default=None,
        alias="fixedProperties",
        description=(
            "Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in"
            " actor_strategies.py."
        ),
    )
    kind: Literal["ActorsQuery"] = "ActorsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    order_by: Optional[list[str]] = Field(default=None, alias="orderBy")
    properties: Optional[
        list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]]
    ] = Field(
        default=None,
        description=(
            "Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in"
            " actor_strategies.py."
        ),
    )
    response: Optional[ActorsQueryResponse] = None
    search: Optional[str] = None
    select: Optional[list[str]] = None
    source: Optional[Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, HogQLQuery]] = None


class DataTableNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    allow_sorting: Optional[bool] = Field(
        default=None,
        alias="allowSorting",
        description="Can the user click on column headers to sort the table? (default: true)",
    )
    columns: Optional[list[str]] = Field(
        default=None, description="Columns shown in the table, unless the `source` provides them."
    )
    embedded: Optional[bool] = Field(default=None, description="Uses the embedded version of LemonTable")
    expandable: Optional[bool] = Field(
        default=None, description="Can expand row to show raw event data (default: true)"
    )
    full: Optional[bool] = Field(default=None, description="Show with most visual options enabled. Used in scenes.")
    hidden_columns: Optional[list[str]] = Field(
        default=None,
        alias="hiddenColumns",
        description="Columns that aren't shown in the table, even if in columns or returned data",
    )
    kind: Literal["DataTableNode"] = "DataTableNode"
    properties_via_url: Optional[bool] = Field(
        default=None, alias="propertiesViaUrl", description="Link properties via the URL (default: false)"
    )
    response: Optional[
        Union[dict[str, Any], Response, Response1, Response2, Response3, Response4, Response5, Response6]
    ] = None
    show_actions: Optional[bool] = Field(
        default=None, alias="showActions", description="Show the kebab menu at the end of the row"
    )
    show_column_configurator: Optional[bool] = Field(
        default=None,
        alias="showColumnConfigurator",
        description="Show a button to configure the table's columns if possible",
    )
    show_date_range: Optional[bool] = Field(default=None, alias="showDateRange", description="Show date range selector")
    show_elapsed_time: Optional[bool] = Field(
        default=None, alias="showElapsedTime", description="Show the time it takes to run a query"
    )
    show_event_filter: Optional[bool] = Field(
        default=None, alias="showEventFilter", description="Include an event filter above the table (EventsNode only)"
    )
    show_export: Optional[bool] = Field(default=None, alias="showExport", description="Show the export button")
    show_hog_ql_editor: Optional[bool] = Field(
        default=None, alias="showHogQLEditor", description="Include a HogQL query editor above HogQL tables"
    )
    show_open_editor_button: Optional[bool] = Field(
        default=None,
        alias="showOpenEditorButton",
        description="Show a button to open the current query as a new insight. (default: true)",
    )
    show_persistent_column_configurator: Optional[bool] = Field(
        default=None,
        alias="showPersistentColumnConfigurator",
        description="Show a button to configure and persist the table's default columns if possible",
    )
    show_property_filter: Optional[bool] = Field(
        default=None, alias="showPropertyFilter", description="Include a property filter above the table"
    )
    show_reload: Optional[bool] = Field(default=None, alias="showReload", description="Show a reload button")
    show_results_table: Optional[bool] = Field(
        default=None, alias="showResultsTable", description="Show a results table"
    )
    show_saved_queries: Optional[bool] = Field(
        default=None, alias="showSavedQueries", description="Shows a list of saved queries"
    )
    show_search: Optional[bool] = Field(
        default=None, alias="showSearch", description="Include a free text search field (PersonsNode only)"
    )
    show_test_account_filters: Optional[bool] = Field(
        default=None, alias="showTestAccountFilters", description="Show filter to exclude test accounts"
    )
    show_timings: Optional[bool] = Field(
        default=None, alias="showTimings", description="Show a detailed query timing breakdown"
    )
    source: Union[
        EventsNode,
        EventsQuery,
        PersonsNode,
        ActorsQuery,
        HogQLQuery,
        TimeToSeeDataSessionsQuery,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebTopClicksQuery,
    ] = Field(..., description="Source of the events")


class HogQLMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    debug: Optional[bool] = Field(
        default=None, description="Enable more verbose output, usually run from the /debug page"
    )
    expr: Optional[str] = Field(
        default=None, description="HogQL expression to validate (use `select` or `expr`, but not both)"
    )
    expr_source: Optional[
        Union[
            EventsNode,
            ActionsNode,
            PersonsNode,
            TimeToSeeDataSessionsQuery,
            EventsQuery,
            ActorsQuery,
            InsightActorsQuery,
            InsightActorsQueryOptions,
            SessionsTimelineQuery,
            HogQuery,
            HogQLQuery,
            HogQLMetadata,
            HogQLAutocomplete,
            WebOverviewQuery,
            WebStatsTableQuery,
            WebTopClicksQuery,
        ]
    ] = Field(
        default=None,
        alias="exprSource",
        description='Query within which "expr" is validated. Defaults to "select * from events"',
    )
    filters: Optional[HogQLFilters] = Field(default=None, description="Extra filters applied to query via {filters}")
    kind: Literal["HogQLMetadata"] = "HogQLMetadata"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[HogQLMetadataResponse] = None
    select: Optional[str] = Field(
        default=None, description="Full select query to validate (use `select` or `expr`, but not both)"
    )
    table: Optional[str] = Field(default=None, description="Table to validate the expression against")


class QueryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    async_: Optional[bool] = Field(
        default=None,
        alias="async",
        description=(
            "(Experimental) Whether to run the query asynchronously. Defaults to False. If True, the `id` of the query"
            " can be used to check the status and to cancel it."
        ),
        examples=[True],
    )
    client_query_id: Optional[str] = Field(
        default=None, description="Client provided query ID. Can be used to retrieve the status or cancel the query."
    )
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        TimeToSeeDataSessionsQuery,
        EventsQuery,
        ActorsQuery,
        InsightActorsQuery,
        InsightActorsQueryOptions,
        SessionsTimelineQuery,
        HogQuery,
        HogQLQuery,
        HogQLMetadata,
        HogQLAutocomplete,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebTopClicksQuery,
        DataVisualizationNode,
        DataTableNode,
        SavedInsightNode,
        InsightVizNode,
        TrendsQuery,
        FunnelsQuery,
        RetentionQuery,
        PathsQuery,
        StickinessQuery,
        LifecycleQuery,
        FunnelCorrelationQuery,
        DatabaseSchemaQuery,
    ] = Field(
        ...,
        description=(
            "Submit a JSON string representing a query for PostHog data analysis, for example a HogQL query.\n\nExample"
            ' payload:\n\n```\n\n{"query": {"kind": "HogQLQuery", "query": "select * from events limit'
            ' 100"}}\n\n```\n\nFor more details on HogQL queries, see the [PostHog HogQL'
            " documentation](/docs/hogql#api-access)."
        ),
        discriminator="kind",
    )
    refresh: Optional[Union[bool, str]] = None


class QuerySchemaRoot(
    RootModel[
        Union[
            EventsNode,
            ActionsNode,
            PersonsNode,
            DataWarehouseNode,
            TimeToSeeDataSessionsQuery,
            EventsQuery,
            ActorsQuery,
            InsightActorsQuery,
            InsightActorsQueryOptions,
            SessionsTimelineQuery,
            HogQuery,
            HogQLQuery,
            HogQLMetadata,
            HogQLAutocomplete,
            WebOverviewQuery,
            WebStatsTableQuery,
            WebTopClicksQuery,
            DataVisualizationNode,
            DataTableNode,
            SavedInsightNode,
            InsightVizNode,
            TrendsQuery,
            FunnelsQuery,
            RetentionQuery,
            PathsQuery,
            StickinessQuery,
            LifecycleQuery,
            FunnelCorrelationQuery,
            DatabaseSchemaQuery,
        ]
    ]
):
    root: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        TimeToSeeDataSessionsQuery,
        EventsQuery,
        ActorsQuery,
        InsightActorsQuery,
        InsightActorsQueryOptions,
        SessionsTimelineQuery,
        HogQuery,
        HogQLQuery,
        HogQLMetadata,
        HogQLAutocomplete,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebTopClicksQuery,
        DataVisualizationNode,
        DataTableNode,
        SavedInsightNode,
        InsightVizNode,
        TrendsQuery,
        FunnelsQuery,
        RetentionQuery,
        PathsQuery,
        StickinessQuery,
        LifecycleQuery,
        FunnelCorrelationQuery,
        DatabaseSchemaQuery,
    ] = Field(..., discriminator="kind")


PropertyGroupFilterValue.model_rebuild()
QueryRequest.model_rebuild()
