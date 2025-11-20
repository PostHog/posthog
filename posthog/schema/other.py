# ruff: noqa: F405  # Star imports are intentional
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel

from posthog.schema.enums import *  # noqa: F403, F401
from posthog.schema.nodes import *  # noqa: F403, F401
from posthog.schema.queries import *  # noqa: F403, F401

if TYPE_CHECKING:
    from posthog.schema.filters import *  # noqa: F403, F401


class AssistantDateRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: str = Field(..., description="ISO8601 date string.")
    date_to: Optional[str] = Field(default=None, description="ISO8601 date string.")


class AssistantDurationRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: str = Field(
        ...,
        description=(
            "Duration in the past. Supported units are: `h` (hour), `d` (day), `w` (week), `m` (month), `y` (year),"
            " `all` (all time). Use the `Start` suffix to define the exact left date boundary. Examples: `-1d` last day"
            " from now, `-180d` last 180 days from now, `mStart` this month start, `-1dStart` yesterday's start."
        ),
    )


class AssistantFormOption(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    href: Optional[str] = Field(
        default=None, description="When href is set, the button opens the link rather than sending an AI message."
    )
    value: str = Field(..., description="Button label, which is also the message that gets sent on click.")
    variant: Optional[str] = Field(
        default=None, description="'primary', 'secondary', or 'tertiary' - default 'secondary'"
    )


class AssistantToolCall(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    args: dict[str, Any]
    id: str
    name: str
    type: Literal["tool_call"] = Field(
        default="tool_call", description="`type` needed to conform to the OpenAI shape, which is expected by LangChain"
    )


class AssistantToolCallMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    tool_call_id: str
    type: Literal["tool"] = "tool"
    ui_payload: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Payload passed through to the frontend - specifically for calls of contextual tool. Tool call messages"
            " without a ui_payload are not passed through to the frontend."
        ),
    )


class AssistantTrendsDisplayType(RootModel[Union[str, Any]]):
    root: Union[str, Any]


class AssistantUpdateEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: str
    tool_call_id: str


class BaseAssistantMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None


class BreakdownValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: float
    value: str


class Results(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    total_count: float
    values: list[BreakdownValue]


class CompareItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: str


class StatusItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: str


class ChartSettingsDisplay(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    color: Optional[str] = None
    displayType: Optional[DisplayType] = None
    label: Optional[str] = None
    trendLine: Optional[bool] = None
    yAxisPosition: Optional[YAxisPosition] = None


class ChartSettingsFormatting(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    decimalPlaces: Optional[float] = None
    prefix: Optional[str] = None
    style: Optional[Style] = None
    suffix: Optional[str] = None


class ConditionalFormattingRule(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: list
    color: str
    colorMode: Optional[ColorMode] = None
    columnName: str
    id: str
    input: str
    templateId: str


class ContextMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    type: Literal["context"] = "context"


class CustomEventConversionGoal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    customEventName: str


class DataWarehouseEventsModifier(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_id_field: str
    id_field: str
    table_name: str
    timestamp_field: str


class DataWarehouseManagedViewsetKind(RootModel[Literal["revenue_analytics"]]):
    root: Literal["revenue_analytics"] = "revenue_analytics"


class DataWarehouseViewLinkConfiguration(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experiments_optimized: Optional[bool] = None
    experiments_timestamp_key: Optional[str] = None


class DatabaseSchemaSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    incremental: bool
    last_synced_at: Optional[str] = None
    name: str
    should_sync: bool
    status: Optional[str] = None


class DatabaseSchemaSource(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    last_synced_at: Optional[str] = None
    prefix: str
    source_type: str
    status: str


class DateRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    explicitDate: Optional[bool] = Field(
        default=False,
        description=(
            "Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of"
            " period."
        ),
    )


class DatetimeDay(RootModel[datetime]):
    root: datetime


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


class EmbeddedDocument(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    document_id: str
    document_type: str
    product: str
    timestamp: datetime


class EmbeddingRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    document_id: str
    document_type: str
    model_name: EmbeddingModelName
    product: str
    rendering: str
    timestamp: datetime


class EndpointLastExecutionTimesRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    names: list[str]


class Population(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    both: float
    exception_only: float
    neither: float
    success_only: float


class ErrorTrackingExplainIssueToolContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    issue_name: str
    stacktrace: str


class FirstEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_id: str
    properties: str
    timestamp: str
    uuid: str


class LastEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_id: str
    properties: str
    timestamp: str
    uuid: str


class VolumeBucket(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: float


class ErrorTrackingIssueAggregations(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    occurrences: float
    sessions: float
    users: float
    volumeRange: Optional[list[float]] = None
    volume_buckets: list[VolumeBucket]


class ErrorTrackingIssueCohort(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: float
    name: str


class ErrorTrackingIssueImpactToolOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[str]


class EventDefinition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    elements: list
    event: str
    properties: dict[str, Any]


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
    person_id: Optional[str] = None
    person_mode: Optional[str] = None
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


class ExperimentExposureTimeSeries(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    days: list[str]
    exposure_counts: list[float]
    variant: str


class ExperimentMaxBayesianContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chance_to_win: float
    credible_interval: list[float] = Field(..., max_length=2, min_length=2)
    key: str
    significant: bool


class ExperimentMaxFrequentistContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    confidence_interval: list[float] = Field(..., max_length=2, min_length=2)
    key: str
    p_value: float
    significant: bool


class ExperimentMetricOutlierHandling(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ignore_zeros: Optional[bool] = None
    lower_bound_percentile: Optional[float] = None
    upper_bound_percentile: Optional[float] = None


class ExperimentVariantFunnelsBaseStats(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    failure_count: float
    key: str
    success_count: float


class ExperimentVariantTrendsBaseStats(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    absolute_exposure: float
    count: float
    exposure: float
    key: str


class FailureMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: Optional[str] = None
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    type: Literal["ai/failure"] = "ai/failure"


class FileSystemEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field_loading: Optional[bool] = Field(
        default=None, alias="_loading", description="Used to indicate pending actions, frontend only"
    )
    created_at: Optional[str] = Field(
        default=None, description="Timestamp when file was added. Used to check persistence"
    )
    href: Optional[str] = Field(default=None, description="Object's URL")
    id: str = Field(..., description="Unique UUID for tree entry")
    last_viewed_at: Optional[str] = Field(
        default=None, description="Timestamp when the file system entry was last viewed"
    )
    meta: Optional[dict[str, Any]] = Field(default=None, description="Metadata")
    path: str = Field(..., description="Object's name and folder")
    ref: Optional[str] = Field(default=None, description="Object's ID or other unique reference")
    shortcut: Optional[bool] = Field(default=None, description="Whether this is a shortcut or the actual item")
    tags: Optional[list[Tag]] = Field(default=None, description="Tag for the product 'beta' / 'alpha'")
    type: Optional[str] = Field(
        default=None, description="Type of object, used for icon, e.g. feature_flag, insight, etc"
    )
    visualOrder: Optional[float] = Field(default=None, description="Order of object in tree")


class FileSystemImport(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field_loading: Optional[bool] = Field(
        default=None, alias="_loading", description="Used to indicate pending actions, frontend only"
    )
    category: Optional[str] = Field(default=None, description="Category label to place this under")
    created_at: Optional[str] = Field(
        default=None, description="Timestamp when file was added. Used to check persistence"
    )
    flag: Optional[str] = None
    href: Optional[str] = Field(default=None, description="Object's URL")
    iconColor: Optional[list[str]] = Field(default=None, description="Color of the icon")
    iconType: Optional[FileSystemIconType] = None
    id: Optional[str] = None
    last_viewed_at: Optional[str] = Field(
        default=None, description="Timestamp when the file system entry was last viewed"
    )
    meta: Optional[dict[str, Any]] = Field(default=None, description="Metadata")
    path: str = Field(..., description="Object's name and folder")
    protocol: Optional[str] = Field(default=None, description='Protocol of the item, defaults to "project://"')
    ref: Optional[str] = Field(default=None, description="Object's ID or other unique reference")
    sceneKey: Optional[str] = Field(default=None, description="Match this with the a base scene key or a specific one")
    sceneKeys: Optional[list[str]] = Field(default=None, description="List of all scenes exported by the app")
    shortcut: Optional[bool] = Field(default=None, description="Whether this is a shortcut or the actual item")
    tags: Optional[list[Tag]] = Field(default=None, description="Tag for the product 'beta' / 'alpha'")
    type: Optional[str] = Field(
        default=None, description="Type of object, used for icon, e.g. feature_flag, insight, etc"
    )
    visualOrder: Optional[float] = Field(default=None, description="Order of object in tree")


class FileSystemViewLogEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ref: str
    type: str
    viewed_at: str


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
    optionalInFunnel: Optional[bool] = None
    order: Optional[float] = None
    type: Optional[EntityType] = None


class FunnelStepsBreakdownResults(RootModel[list[list[dict[str, Any]]]]):
    root: list[list[dict[str, Any]]]


class FunnelStepsResults(RootModel[list[dict[str, Any]]]):
    root: list[dict[str, Any]]


class FunnelTimeToConvertResults(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    average_conversion_time: Optional[float] = None
    bins: list[list[int]]


class FunnelTrendsResults(RootModel[list[dict[str, Any]]]):
    root: list[dict[str, Any]]


class GoalLine(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    borderColor: Optional[str] = None
    displayIfCrossed: Optional[bool] = None
    displayLabel: Optional[bool] = None
    label: str
    position: Optional[Position] = None
    value: float


class HogCompileResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: list
    locals: list


class HogQLVariable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code_name: str
    isNull: Optional[bool] = None
    value: Optional[Any] = None
    variableId: str


class InsightsThresholdBounds(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lower: Optional[float] = None
    upper: Optional[float] = None


class LLMTraceEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    createdAt: str
    event: Union[AIEventType, str]
    id: str
    properties: dict[str, Any]


class LLMTracePerson(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created_at: str
    distinct_id: str
    properties: dict[str, Any]
    uuid: str


class MatchedRecordingEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    timestamp: str
    uuid: str


class MatchingEventsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    results: list[MatchedRecordingEvent]


class MaxActionContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Optional[str] = None
    id: float
    name: str
    type: Literal["action"] = "action"


class MaxAddonInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    current_usage: float
    description: str
    docs_url: Optional[str] = None
    has_exceeded_limit: bool
    is_used: bool
    name: str
    percentage_usage: Optional[float] = None
    projected_amount_usd: Optional[str] = None
    projected_amount_usd_with_limit: Optional[str] = None
    type: str
    usage_limit: Optional[float] = None


class SpendHistoryItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_type: Optional[BillingSpendResponseBreakdownType] = None
    breakdown_value: Optional[Union[str, list[str]]] = None
    data: list[float]
    dates: list[str]
    id: float
    label: str


class UsageHistoryItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_type: Optional[BillingUsageResponseBreakdownType] = None
    breakdown_value: Optional[Union[str, list[str]]] = None
    data: list[float]
    dates: list[str]
    id: float
    label: str


class MaxBillingContextSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active_destinations: float
    autocapture_on: bool


class MaxBillingContextTrial(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    expires_at: Optional[str] = None
    is_active: bool
    target: Optional[str] = None


class MaxEventContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Optional[str] = None
    id: str
    name: Optional[str] = None
    type: Literal["event"] = "event"


class MaxExperimentVariantResultBayesian(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chance_to_win: Optional[float] = None
    credible_interval: Optional[list[float]] = None
    key: str
    significant: bool


class MaxExperimentVariantResultFrequentist(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    confidence_interval: Optional[list[float]] = None
    key: str
    p_value: Optional[float] = None
    significant: bool


class MaxProductInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    addons: list[MaxAddonInfo]
    current_usage: Optional[float] = None
    custom_limit_usd: Optional[float] = None
    description: str
    docs_url: Optional[str] = None
    has_exceeded_limit: bool
    is_used: bool
    name: str
    next_period_custom_limit_usd: Optional[float] = None
    percentage_usage: float
    projected_amount_usd: Optional[str] = None
    projected_amount_usd_with_limit: Optional[str] = None
    type: str
    usage_limit: Optional[float] = None


class MinimalHedgehogConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    accessories: list[str]
    color: Optional[HedgehogColorOptions] = None
    use_as_profile: bool


class PageURL(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: float
    url: str


class PathsLink(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    average_conversion_time: float
    source: str
    target: str
    value: float


class PersistedFolder(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created_at: str
    id: str
    path: str
    protocol: str
    type: str
    updated_at: str


class PersonType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created_at: Optional[str] = None
    distinct_ids: list[str]
    id: Optional[str] = None
    is_identified: Optional[bool] = None
    name: Optional[str] = None
    properties: dict[str, Any]
    uuid: Optional[str] = None


class PlaywrightWorkspaceSetupData(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    organization_name: Optional[str] = None


class PlaywrightWorkspaceSetupResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    organization_id: str
    organization_name: str
    personal_api_key: str
    team_id: str
    team_name: str
    user_email: str
    user_id: str


class ProductItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    category: Optional[str] = None
    iconType: Optional[str] = None
    path: str
    type: Optional[str] = None


class ProductsData(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    games: list[ProductItem]
    metadata: list[ProductItem]
    products: list[ProductItem]


class Mark(BaseModel):
    attrs: Optional[dict[str, Any]] = None
    type: str


class ProsemirrorJSONContent(BaseModel):
    attrs: Optional[dict[str, Any]] = None
    content: Optional[list[ProsemirrorJSONContent]] = None
    marks: Optional[list[Mark]] = None
    text: Optional[str] = None
    type: Optional[str] = None


class QueryLogTags(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    productKey: Optional[str] = Field(
        default=None,
        description=(
            "Product responsible for this query. Use string, there's no need to churn the Schema when we add a new"
            " product *"
        ),
    )
    scene: Optional[str] = Field(
        default=None,
        description=(
            "Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a"
            " new Scene *"
        ),
    )


class QueryResponseAlternative7(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: Optional[list] = None
    coloredBytecode: Optional[list] = None
    results: Any
    stdout: Optional[str] = None


class QueryResponseAlternative21(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: DateRange
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    timeseries: list[ExperimentExposureTimeSeries]
    total_exposures: dict[str, float]


class QueryResponseAlternative71(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    questions: list[str]


class QueryTiming(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    k: str = Field(..., description="Key. Shortened to 'k' to save on data.")
    t: float = Field(..., description="Time in seconds. Shortened to 't' to save on data.")


class ReasoningMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    substeps: Optional[list[str]] = None
    type: Literal["ai/reasoning"] = "ai/reasoning"


class ResolvedDateRangeResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: datetime
    date_to: datetime


class ResultCustomizationBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    color: Optional[DataColorToken] = None
    hidden: Optional[bool] = None


class ResultCustomizationByPosition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignmentBy: Literal["position"] = "position"
    color: Optional[DataColorToken] = None
    hidden: Optional[bool] = None


class ResultCustomizationByValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignmentBy: Literal["value"] = "value"
    color: Optional[DataColorToken] = None
    hidden: Optional[bool] = None


class RevenueAnalyticsBreakdown(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str
    type: Literal["revenue_analytics"] = "revenue_analytics"


class RevenueAnalyticsGoal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    due_date: str
    goal: float
    mrr_or_gross: Optional[MrrOrGross] = MrrOrGross.GROSS
    name: str


class RevenueAnalyticsMRRQueryResultItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    churn: Any
    contraction: Any
    expansion: Any
    new: Any
    total: Any


class RevenueCurrencyPropertyConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: Optional[str] = None
    static: Optional[CurrencyCode] = None


class SamplingRate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator: Optional[float] = None
    numerator: float


class SessionData(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    event_uuid: str
    person_id: str
    session_id: str
    timestamp: str


class SessionEventsItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[list] = Field(
        ...,
        description="List of events for this session, each event is a list of field values matching the query columns",
    )
    session_id: str = Field(..., description="Session ID these events belong to")


class SharingConfigurationSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    detailed: Optional[bool] = None
    hideExtraDetails: Optional[bool] = None
    legend: Optional[bool] = None
    noHeader: Optional[bool] = None
    showInspector: Optional[bool] = None
    whitelabel: Optional[bool] = None


class SimilarIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str
    distance: float
    first_seen: str
    id: str
    library: Optional[str] = None
    name: str
    status: str


class SourceFieldFileUploadJsonFormatConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal[".json"] = ".json"
    keys: Union[str, list[str]]


class SourceFieldOauthConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: str
    label: str
    name: str
    required: bool
    type: Literal["oauth"] = "oauth"


class SourceFieldSSHTunnelConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    name: str
    type: Literal["ssh-tunnel"] = "ssh-tunnel"


class SourceMap(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    campaign: Optional[str] = None
    clicks: Optional[str] = None
    cost: Optional[str] = None
    currency: Optional[str] = None
    date: Optional[str] = None
    impressions: Optional[str] = None
    reported_conversion: Optional[str] = None
    source: Optional[str] = None


class SuggestedTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    table: str
    tooltip: Optional[str] = None


class SurveyAnalysisResponseItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    isOpenEnded: Optional[bool] = Field(default=True, description="Whether this is an open-ended response")
    responseText: Optional[str] = Field(default="", description="The response text content")
    timestamp: Optional[str] = Field(default="", description="Response timestamp")


class Value(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: float
    name: str


class Actions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    values: list[Value]


class Branching(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    index: Optional[float] = None
    responseValues: Optional[dict[str, Union[str, float]]] = None
    type: SurveyQuestionBranchingType


class TestSetupRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: Optional[dict[str, Any]] = None


class TestSetupResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    available_tests: Optional[list[str]] = None
    error: Optional[str] = None
    result: Optional[Any] = None
    success: bool
    test_name: str


class TimelineEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[EventType]
    recording_duration_s: Optional[float] = Field(default=None, description="Duration of the recording in seconds.")
    sessionId: Optional[str] = Field(default=None, description="Session ID. None means out-of-session events")


class UserBasicType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_id: str
    email: str
    first_name: str
    hedgehog_config: Optional[MinimalHedgehogConfig] = None
    id: float
    is_email_verified: Optional[Any] = None
    last_name: Optional[str] = None
    role_at_organization: Optional[str] = None
    uuid: str


class VectorSearchResponseItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distance: float
    id: str


class ActionsPie(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    disableHoverOffset: Optional[bool] = None
    hideAggregation: Optional[bool] = None


class RETENTION(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hideLineGraph: Optional[bool] = None
    hideSizeColumn: Optional[bool] = None
    useSmallLayout: Optional[bool] = None


class VizSpecificOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ActionsPie_1: Optional[ActionsPie] = Field(default=None, alias="ActionsPie")
    RETENTION_1: Optional[RETENTION] = Field(default=None, alias="RETENTION")


class WebAnalyticsExternalSummaryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: str
    date_to: str
    explicit_date: Optional[bool] = None


class WebAnalyticsSampling(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    enabled: Optional[bool] = None
    forceSamplingRate: Optional[SamplingRate] = None


class WebOverviewItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: Optional[float] = None
    isIncreaseBad: Optional[bool] = None
    key: str
    kind: WebAnalyticsItemKind
    previous: Optional[float] = None
    usedPreAggregatedTables: Optional[bool] = None
    value: Optional[float] = None


class Metrics(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    Bounces: Optional[float] = None
    PageViews: Optional[float] = None
    SessionDuration: Optional[float] = None
    Sessions: Optional[float] = None
    TotalSessions: Optional[float] = None
    UniqueUsers: Optional[float] = None


class WebTrendsItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bucket: str
    metrics: Metrics


class WebVitalsPathBreakdownResultItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    path: str
    value: float


class YAxisSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    scale: Optional[Scale] = None
    showGridLines: Optional[bool] = None
    showTicks: Optional[bool] = None
    startAtZero: Optional[bool] = Field(default=None, description="Whether the Y axis should start at zero")


class Integer(RootModel[int]):
    root: int


class ActionConversionGoal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: int


class ActorsPropertyTaxonomyResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    sample_count: int
    sample_values: list[Union[str, float, bool, int]]


class AlertCondition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: AlertConditionType


class AssistantForm(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    options: list[AssistantFormOption]


class AssistantGenerationStatusEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: AssistantGenerationStatusType


class AssistantMessageMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    form: Optional[AssistantForm] = None
    thinking: Optional[list[dict[str, Any]]] = None


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
    insertText: str = Field(
        ..., description="A string or snippet that should be inserted in a document when selecting this completion."
    )
    kind: AutocompleteCompletionItemKind = Field(
        ..., description="The kind of this completion item. Based on the kind an icon is chosen by the editor."
    )
    label: str = Field(
        ...,
        description=(
            "The label of this completion item. By default this is also the text that is inserted when selecting this"
            " completion."
        ),
    )


class Breakdown(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: Optional[int] = None
    histogram_bin_count: Optional[int] = None
    normalize_url: Optional[bool] = None
    property: Union[str, int]
    type: Optional[MultipleBreakdownType] = None


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


class Settings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    display: Optional[ChartSettingsDisplay] = None
    formatting: Optional[ChartSettingsFormatting] = None


class ChartAxis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    column: str
    settings: Optional[Settings] = None


class ChartSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    goalLines: Optional[list[GoalLine]] = None
    leftYAxisSettings: Optional[YAxisSettings] = None
    rightYAxisSettings: Optional[YAxisSettings] = None
    seriesBreakdownColumn: Optional[str] = None
    showLegend: Optional[bool] = None
    showTotalRow: Optional[bool] = None
    showXAxisBorder: Optional[bool] = None
    showXAxisTicks: Optional[bool] = None
    showYAxisBorder: Optional[bool] = None
    stackBars100: Optional[bool] = Field(default=None, description="Whether we fill the bars to 100% in stacked mode")
    xAxis: Optional[ChartAxis] = None
    yAxis: Optional[list[ChartAxis]] = None
    yAxisAtZero: Optional[bool] = Field(
        default=None, description="Deprecated: use `[left|right]YAxisSettings`. Whether the Y axis should start at zero"
    )


class ClickhouseQueryProgress(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active_cpu_time: int
    bytes_read: int
    estimated_rows_total: int
    rows_read: int
    time_elapsed: int


class CustomChannelCondition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    key: CustomChannelField
    op: CustomChannelOperator
    value: Optional[Union[str, list[str]]] = None


class CustomChannelRule(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    channel_type: str
    combiner: FilterLogicalOperator
    id: str
    items: list[CustomChannelCondition]


class DataTableNodeViewPropsContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    eventDefinitionId: Optional[str] = None
    type: DataTableNodeViewPropsContextType


class DataWarehouseViewLink(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    configuration: Optional[DataWarehouseViewLinkConfiguration] = None
    created_at: Optional[str] = None
    created_by: Optional[UserBasicType] = None
    field_name: Optional[str] = None
    id: str
    joining_table_key: Optional[str] = None
    joining_table_name: Optional[str] = None
    source_table_key: Optional[str] = None
    source_table_name: Optional[str] = None


class DatabaseSchemaField(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chain: Optional[list[Union[str, int]]] = None
    fields: Optional[list[str]] = None
    hogql_value: str
    id: Optional[str] = None
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
    row_count: Optional[float] = None
    type: Literal["posthog"] = "posthog"


class DatabaseSchemaSystemTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    row_count: Optional[float] = None
    type: Literal["system"] = "system"


class DatabaseSchemaTableCommon(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    row_count: Optional[float] = None
    type: DatabaseSchemaTableType


class Day(RootModel[int]):
    root: int


class DeepResearchNotebook(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    category: Literal["deep_research"] = "deep_research"
    notebook_id: str
    notebook_type: Optional[DeepResearchType] = None
    title: str


class EmbeddingDistance(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distance: float
    origin: Optional[EmbeddingRecord] = None
    result: EmbeddingRecord


class ErrorTrackingExternalReferenceIntegration(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    display_name: str
    id: float
    kind: IntegrationKind


class ErrorTrackingIssueAssignee(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Union[str, int]
    type: ErrorTrackingIssueAssigneeType


class EventOddsRatioSerialized(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    correlation_type: CorrelationType
    event: EventDefinition
    failure_count: int
    odds_ratio: float
    success_count: int


class EventTaxonomyItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str
    sample_count: int
    sample_values: list[str]


class EventsHeatMapColumnAggregationResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    column: int
    value: int


class EventsHeatMapDataResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    column: int
    row: int
    value: int


class EventsHeatMapRowAggregationResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    row: int
    value: int


class EventsHeatMapStructuredResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    allAggregations: int
    columnAggregations: list[EventsHeatMapColumnAggregationResult]
    data: list[EventsHeatMapDataResult]
    rowAggregations: list[EventsHeatMapRowAggregationResult]


class ExperimentMetricBaseProperties(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownFilter: Optional[BreakdownFilter] = None
    conversion_window: Optional[int] = None
    conversion_window_unit: Optional[FunnelConversionWindowTimeUnit] = None
    fingerprint: Optional[str] = None
    goal: Optional[ExperimentMetricGoal] = None
    isSharedMetric: Optional[bool] = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    name: Optional[str] = None
    response: Optional[dict[str, Any]] = None
    sharedMetricId: Optional[float] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentStatsBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator_sum: Optional[float] = None
    denominator_sum_squares: Optional[float] = None
    key: str
    number_of_samples: int
    numerator_denominator_sum_product: Optional[float] = None
    step_counts: Optional[list[int]] = None
    step_sessions: Optional[list[list[SessionData]]] = None
    sum: float
    sum_squares: float


class ExperimentStatsBaseValidated(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator_sum: Optional[float] = None
    denominator_sum_squares: Optional[float] = None
    key: str
    number_of_samples: int
    numerator_denominator_sum_product: Optional[float] = None
    step_counts: Optional[list[int]] = None
    step_sessions: Optional[list[list[SessionData]]] = None
    sum: float
    sum_squares: float
    validation_failures: Optional[list[ExperimentStatsValidationFailure]] = None


class ExperimentVariantResultBayesian(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chance_to_win: Optional[float] = None
    credible_interval: Optional[list[float]] = Field(default=None, max_length=2, min_length=2)
    denominator_sum: Optional[float] = None
    denominator_sum_squares: Optional[float] = None
    key: str
    method: Literal["bayesian"] = "bayesian"
    number_of_samples: int
    numerator_denominator_sum_product: Optional[float] = None
    significant: Optional[bool] = None
    step_counts: Optional[list[int]] = None
    step_sessions: Optional[list[list[SessionData]]] = None
    sum: float
    sum_squares: float
    validation_failures: Optional[list[ExperimentStatsValidationFailure]] = None


class ExperimentVariantResultFrequentist(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    confidence_interval: Optional[list[float]] = Field(default=None, max_length=2, min_length=2)
    denominator_sum: Optional[float] = None
    denominator_sum_squares: Optional[float] = None
    key: str
    method: Literal["frequentist"] = "frequentist"
    number_of_samples: int
    numerator_denominator_sum_product: Optional[float] = None
    p_value: Optional[float] = None
    significant: Optional[bool] = None
    step_counts: Optional[list[int]] = None
    step_sessions: Optional[list[list[SessionData]]] = None
    sum: float
    sum_squares: float
    validation_failures: Optional[list[ExperimentStatsValidationFailure]] = None


class ExternalQueryError(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: ExternalQueryErrorCode
    detail: str


class FileSystemCount(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: float
    entries: list[FileSystemEntry]
    has_more: bool


class FunnelCorrelationResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[EventOddsRatioSerialized]
    skewed: bool


class FunnelExclusionSteps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelFromStep: int
    funnelToStep: int


class HogQLAutocompleteResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incomplete_list: bool = Field(..., description="Whether or not the suggestions returned are complete")
    suggestions: list[AutocompleteCompletionItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class HogQLNotice(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    end: Optional[int] = None
    fix: Optional[str] = None
    message: str
    start: Optional[int] = None


class HogQLQueryModifiers(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bounceRateDurationSeconds: Optional[float] = None
    bounceRatePageViewMode: Optional[BounceRatePageViewMode] = None
    convertToProjectTimezone: Optional[bool] = None
    customChannelTypeRules: Optional[list[CustomChannelRule]] = None
    dataWarehouseEventsModifiers: Optional[list[DataWarehouseEventsModifier]] = None
    debug: Optional[bool] = None
    formatCsvAllowDoubleQuotes: Optional[bool] = None
    inCohortVia: Optional[InCohortVia] = None
    materializationMode: Optional[MaterializationMode] = None
    optimizeJoinedFilters: Optional[bool] = None
    optimizeProjections: Optional[bool] = None
    personsArgMaxVersion: Optional[PersonsArgMaxVersion] = None
    personsJoinMode: Optional[PersonsJoinMode] = None
    personsOnEventsMode: Optional[PersonsOnEventsMode] = None
    propertyGroupsMode: Optional[PropertyGroupsMode] = None
    s3TableUseInvalidColumns: Optional[bool] = None
    sessionTableVersion: Optional[SessionTableVersion] = None
    sessionsV2JoinMode: Optional[SessionsV2JoinMode] = None
    timings: Optional[bool] = None
    useMaterializedViews: Optional[bool] = None
    usePreaggregatedTableTransforms: Optional[bool] = Field(
        default=None,
        description="Try to automatically convert HogQL queries to use preaggregated tables at the AST level *",
    )
    usePresortedEventsTable: Optional[bool] = None
    useWebAnalyticsPreAggregatedTables: Optional[bool] = None


class DayItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: Union[str, datetime, int]


class InsightThreshold(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bounds: Optional[InsightsThresholdBounds] = None
    type: InsightThresholdType


class LLMTrace(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aiSessionId: Optional[str] = None
    createdAt: str
    errorCount: Optional[float] = None
    events: list[LLMTraceEvent]
    id: str
    inputCost: Optional[float] = None
    inputState: Optional[Any] = None
    inputTokens: Optional[float] = None
    outputCost: Optional[float] = None
    outputState: Optional[Any] = None
    outputTokens: Optional[float] = None
    person: LLMTracePerson
    totalCost: Optional[float] = None
    totalLatency: Optional[float] = None
    traceName: Optional[str] = None


class LogMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    attributes: dict[str, Any]
    body: str
    event_name: str
    instrumentation_scope: str
    level: LogSeverityLevel
    observed_timestamp: datetime
    resource_attributes: Any
    severity_number: float
    severity_text: LogSeverityLevel
    span_id: str
    timestamp: datetime
    trace_id: str
    uuid: str


class MarketingAnalyticsItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: Optional[float] = None
    hasComparison: Optional[bool] = None
    isIncreaseBad: Optional[bool] = None
    key: str
    kind: WebAnalyticsItemKind
    previous: Optional[Union[float, str]] = None
    value: Optional[Union[float, str]] = None


class MarketingAnalyticsSchemaField(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    isCurrency: bool
    required: bool
    type: list[MarketingAnalyticsSchemaFieldTypes]


class MatchedRecording(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[MatchedRecordingEvent]
    session_id: Optional[str] = None


class MaxBillingContextBillingPeriod(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    current_period_end: str
    current_period_start: str
    interval: MaxBillingContextBillingPeriodInterval


class MaxExperimentMetricResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str
    variant_results: list[Union[MaxExperimentVariantResultBayesian, MaxExperimentVariantResultFrequentist]]


class MaxExperimentSummaryContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Optional[str] = None
    experiment_id: Union[float, str]
    experiment_name: str
    exposures: Optional[dict[str, float]] = None
    primary_metrics_results: list[MaxExperimentMetricResult]
    secondary_metrics_results: list[MaxExperimentMetricResult]
    stats_method: ExperimentStatsMethod
    variants: list[str]


class NotebookUpdateMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: ProsemirrorJSONContent
    conversation_notebooks: Optional[list[DeepResearchNotebook]] = None
    current_run_notebooks: Optional[list[DeepResearchNotebook]] = None
    id: Optional[str] = None
    notebook_id: str
    notebook_type: Literal["deep_research"] = "deep_research"
    parent_tool_call_id: Optional[str] = None
    tool_calls: Optional[list[AssistantToolCall]] = None
    type: Literal["ai/notebook"] = "ai/notebook"


class PlanningStep(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str
    status: PlanningStepStatus


class QueryResponseAlternative9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ch_table_names: Optional[list[str]] = None
    errors: list[HogQLNotice]
    isUsingIndices: Optional[QueryIndexUsage] = None
    isValid: Optional[bool] = None
    notices: list[HogQLNotice]
    query: Optional[str] = None
    table_names: Optional[list[str]] = None
    warnings: list[HogQLNotice]


class QueryResponseAlternative10(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incomplete_list: bool = Field(..., description="Whether or not the suggestions returned are complete")
    suggestions: list[AutocompleteCompletionItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative29(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: dict[str, Any]
    error: Optional[ExternalQueryError] = None
    status: ExternalQueryStatus


class QueryStatus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    complete: Optional[bool] = Field(
        default=False,
        description=(
            "Whether the query is still running. Will be true if the query is complete, even if it errored. Either"
            " result or error will be set."
        ),
    )
    dashboard_id: Optional[int] = None
    end_time: Optional[datetime] = Field(
        default=None, description="When did the query execution task finish (whether successfully or not)."
    )
    error: Optional[bool] = Field(
        default=False,
        description=(
            "If the query failed, this will be set to true. More information can be found in the error_message field."
        ),
    )
    error_message: Optional[str] = None
    expiration_time: Optional[datetime] = None
    id: str
    insight_id: Optional[int] = None
    labels: Optional[list[str]] = None
    pickup_time: Optional[datetime] = Field(
        default=None, description="When was the query execution task picked up by a worker."
    )
    query_async: Literal[True] = Field(default=True, description="ONLY async queries use QueryStatus.")
    query_progress: Optional[ClickhouseQueryProgress] = None
    results: Optional[Any] = None
    start_time: Optional[datetime] = Field(default=None, description="When was query execution task enqueued.")
    task_id: Optional[str] = None
    team_id: int


class QueryStatusResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    query_status: QueryStatus


class ResultCustomization(RootModel[Union[ResultCustomizationByValue, ResultCustomizationByPosition]]):
    root: Union[ResultCustomizationByValue, ResultCustomizationByPosition]


class RetentionValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: int
    label: Optional[str] = None


class RevenueAnalyticsEventItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    couponProperty: Optional[str] = Field(
        default=None,
        description=(
            "Property used to identify whether the revenue event is connected to a coupon Useful when trying to break"
            " revenue down by a specific coupon"
        ),
    )
    currencyAwareDecimal: Optional[bool] = Field(
        default=False,
        description=(
            "If true, the revenue will be divided by the smallest unit of the currency.\n\nFor example, in case this is"
            " set to true, if the revenue is 1089 and the currency is USD, the revenue will be $10.89, but if the"
            " currency is JPY, the revenue will be ¥1089."
        ),
    )
    eventName: str
    productProperty: Optional[str] = Field(
        default=None,
        description=(
            "Property used to identify what product the revenue event refers to Useful when trying to break revenue"
            " down by a specific product"
        ),
    )
    revenueCurrencyProperty: Optional[RevenueCurrencyPropertyConfig] = Field(
        default_factory=lambda: RevenueCurrencyPropertyConfig.model_validate({"static": "USD"}),
        description=(
            "TODO: In the future, this should probably be renamed to `currencyProperty` to follow the pattern above"
        ),
    )
    revenueProperty: str
    subscriptionDropoffDays: Optional[float] = Field(
        default=45,
        description=(
            "The number of days we still consider a subscription to be active after the last event. This is useful to"
            " avoid the current month's data to look as if most of the subscriptions have churned since we might not"
            " have an event for the current month."
        ),
    )
    subscriptionDropoffMode: Optional[SubscriptionDropoffMode] = Field(
        default=SubscriptionDropoffMode.LAST_EVENT,
        description=(
            "After a subscription has dropped off, when should we consider it to have ended? It should either be at the"
            " date of the last event (will alter past periods, the default), or at the date of the last event plus the"
            " dropoff period."
        ),
    )
    subscriptionProperty: Optional[str] = Field(
        default=None,
        description=(
            "Property used to identify what subscription the revenue event refers to Useful when trying to detect"
            " churn/LTV/ARPU/etc."
        ),
    )


class RevenueAnalyticsOverviewItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: RevenueAnalyticsOverviewItemKey
    value: float


class SessionRecordingType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active_seconds: Optional[float] = None
    activity_score: Optional[float] = Field(
        default=None, description="calculated on the backend so that we can sort by it, definition may change over time"
    )
    click_count: Optional[float] = None
    console_error_count: Optional[float] = None
    console_log_count: Optional[float] = None
    console_warn_count: Optional[float] = None
    distinct_id: Optional[str] = None
    email: Optional[str] = None
    end_time: str = Field(..., description="When the recording ends in ISO format.")
    expiry_time: Optional[str] = Field(default=None, description="When the recording expires, in ISO format.")
    id: str
    inactive_seconds: Optional[float] = None
    keypress_count: Optional[float] = None
    matching_events: Optional[list[MatchedRecording]] = Field(default=None, description="List of matching events. *")
    mouse_activity_count: Optional[float] = Field(
        default=None, description="count of all mouse activity in the recording, not just clicks"
    )
    ongoing: Optional[bool] = Field(
        default=None,
        description=(
            "whether we have received data for this recording in the last 5 minutes (assumes the recording was loaded"
            " from ClickHouse)\n*"
        ),
    )
    person: Optional[PersonType] = None
    recording_duration: float = Field(..., description="Length of recording in seconds.")
    recording_ttl: Optional[float] = Field(
        default=None, description="Number of whole days left until the recording expires."
    )
    retention_period_days: Optional[float] = Field(default=None, description="retention period for this recording")
    snapshot_source: SnapshotSource
    start_time: str = Field(..., description="When the recording starts in ISO format.")
    start_url: Optional[str] = None
    storage: Optional[Storage] = Field(default=None, description="Where this recording information was loaded from")
    summary: Optional[str] = None
    viewed: bool = Field(..., description="Whether this recording has been viewed by you already.")
    viewers: list[str] = Field(..., description="user ids of other users who have viewed this recording")


class SourceFieldFileUploadConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fileFormat: SourceFieldFileUploadJsonFormatConfig
    label: str
    name: str
    required: bool
    type: Literal["file-upload"] = "file-upload"


class SourceFieldInputConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    name: str
    placeholder: str
    required: bool
    type: SourceFieldInputConfigType


class StickinessCriteria(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: StickinessOperator
    value: int


class SurveyAnalysisQuestionGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    questionId: Optional[str] = Field(default="unknown", description="Question identifier")
    questionName: Optional[str] = Field(default="Unknown question", description="Question text")
    responses: Optional[list[SurveyAnalysisResponseItem]] = Field(
        default=[], description="List of responses for this question"
    )


class SurveyAppearanceSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    backgroundColor: Optional[str] = None
    borderColor: Optional[str] = None
    buttonColor: Optional[str] = None
    buttonTextColor: Optional[str] = None
    inputBackground: Optional[str] = None
    maxWidth: Optional[str] = None
    placeholder: Optional[str] = None
    position: Optional[SurveyPosition] = None
    ratingButtonActiveColor: Optional[str] = None
    ratingButtonColor: Optional[str] = None
    shuffleQuestions: Optional[bool] = None
    surveyPopupDelaySeconds: Optional[float] = None
    tabPosition: Optional[SurveyTabPosition] = None
    textColor: Optional[str] = None
    textSubtleColor: Optional[str] = None
    thankYouMessageCloseButtonText: Optional[str] = None
    thankYouMessageDescription: Optional[str] = None
    thankYouMessageDescriptionContentType: Optional[SurveyQuestionDescriptionContentType] = None
    thankYouMessageHeader: Optional[str] = None
    whiteLabel: Optional[bool] = None
    widgetColor: Optional[str] = None
    widgetLabel: Optional[str] = None
    widgetSelector: Optional[str] = None
    widgetType: Optional[SurveyWidgetType] = None
    zIndex: Optional[str] = None


class SurveyDisplayConditionsSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions: Optional[Actions] = None
    deviceTypes: Optional[list[str]] = None
    deviceTypesMatchType: Optional[SurveyMatchType] = None
    linkedFlagVariant: Optional[str] = None
    seenSurveyWaitPeriodInDays: Optional[float] = None
    selector: Optional[str] = None
    url: Optional[str] = None
    urlMatchType: Optional[SurveyMatchType] = None


class SurveyQuestionSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    branching: Optional[Branching] = None
    buttonText: Optional[str] = None
    choices: Optional[list[str]] = None
    description: Optional[str] = None
    descriptionContentType: Optional[SurveyQuestionDescriptionContentType] = None
    display: Optional[Display1] = None
    hasOpenChoice: Optional[bool] = None
    id: Optional[str] = None
    link: Optional[str] = None
    lowerBoundLabel: Optional[str] = None
    optional: Optional[bool] = None
    question: str
    scale: Optional[float] = None
    shuffleOptions: Optional[bool] = None
    type: SurveyQuestionType
    upperBoundLabel: Optional[str] = None


class TableSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[ChartAxis]] = None
    conditionalFormatting: Optional[list[ConditionalFormattingRule]] = None


class TaskExecutionItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    artifact_ids: Optional[list[str]] = None
    description: str
    id: str
    progress_text: Optional[str] = None
    prompt: str
    status: TaskExecutionStatus
    task_type: str


class TaskExecutionMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    tasks: list[TaskExecutionItem]
    type: Literal["ai/task_execution"] = "ai/task_execution"


class TeamTaxonomyItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: int
    event: str


class TrendsAlertConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    check_ongoing_interval: Optional[bool] = None
    series_index: int
    type: Literal["TrendsAlertConfig"] = "TrendsAlertConfig"


class UsageMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    change_from_previous_pct: Optional[float] = None
    display: UsageMetricDisplay
    format: UsageMetricFormat
    id: str
    interval: int
    name: str
    previous: float
    value: float


class WebAnalyticsItemBaseNumberString(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: Optional[float] = None
    isIncreaseBad: Optional[bool] = None
    key: str
    kind: WebAnalyticsItemKind
    previous: Optional[Union[float, str]] = None
    value: Optional[Union[float, str]] = None


class WebAnalyticsItemBaseNumber(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: Optional[float] = None
    isIncreaseBad: Optional[bool] = None
    key: str
    kind: WebAnalyticsItemKind
    previous: Optional[float] = None
    value: Optional[float] = None


class WebVitalsItemAction(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: WebVitalsMetric
    math: WebVitalsPercentile


class WebVitalsPathBreakdownResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    good: list[WebVitalsPathBreakdownResultItem]
    needs_improvements: list[WebVitalsPathBreakdownResultItem]
    poor: list[WebVitalsPathBreakdownResultItem]


class AnalyticsQueryResponseBase(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class AssistantFunnelNodeShared(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    math: Optional[AssistantFunnelsMath] = Field(
        default=None,
        description=(
            "Optional math aggregation type for the series. Only specify this math type if the user wants one of these."
            " `first_time_for_user` - counts the number of users who have completed the event for the first time ever."
            " `first_time_for_user_with_filters` - counts the number of users who have completed the event with"
            " specified filters for the first time."
        ),
    )
    properties: Optional[
        list[
            Union[
                Union[
                    AssistantGenericPropertyFilter1,
                    AssistantGenericPropertyFilter2,
                    AssistantGenericPropertyFilter3,
                    AssistantGenericPropertyFilter4,
                    AssistantGenericPropertyFilter5,
                ],
                Union[
                    AssistantGroupPropertyFilter1,
                    AssistantGroupPropertyFilter2,
                    AssistantGroupPropertyFilter3,
                    AssistantGroupPropertyFilter4,
                    AssistantGroupPropertyFilter5,
                ],
            ]
        ]
    ] = None


class AssistantInsightsQueryBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[Union[AssistantDateRange, AssistantDurationRange]] = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    properties: Optional[
        list[
            Union[
                Union[
                    AssistantGenericPropertyFilter1,
                    AssistantGenericPropertyFilter2,
                    AssistantGenericPropertyFilter3,
                    AssistantGenericPropertyFilter4,
                    AssistantGenericPropertyFilter5,
                ],
                Union[
                    AssistantGroupPropertyFilter1,
                    AssistantGroupPropertyFilter2,
                    AssistantGroupPropertyFilter3,
                    AssistantGroupPropertyFilter4,
                    AssistantGroupPropertyFilter5,
                ],
            ]
        ]
    ] = Field(default=[], description="Property filters for all series")
    samplingFactor: Optional[float] = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )


class AssistantMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: Optional[str] = None
    meta: Optional[AssistantMessageMetadata] = None
    parent_tool_call_id: Optional[str] = None
    tool_calls: Optional[list[AssistantToolCall]] = None
    type: Literal["ai"] = "ai"


class BreakdownItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: str
    value: Union[str, int]


class CacheMissResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: Optional[str] = None
    query_status: Optional[QueryStatus] = None


class CachedFunnelCorrelationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: FunnelCorrelationResult
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CalendarHeatmapResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = Field(default=None, description="Wether more breakdown values are available.")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: EventsHeatMapStructuredResult
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
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
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list[str]] = None


class Response2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class Response4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: Optional[bool] = None


class Response5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None
    usedPreAggregatedTables: Optional[bool] = None


class Response6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class Response8(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class Response10(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class Response11(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response12(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response13(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response14(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response15(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response16(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class Response18(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class Response19(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response24(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class DatabaseSchemaBatchExportTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    row_count: Optional[float] = None
    type: Literal["batch_export"] = "batch_export"


class DatabaseSchemaDataWarehouseTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    format: str
    id: str
    name: str
    row_count: Optional[float] = None
    schema_: Optional[DatabaseSchemaSchema] = Field(default=None, alias="schema")
    source: Optional[DatabaseSchemaSource] = None
    type: Literal["data_warehouse"] = "data_warehouse"
    url_pattern: str


class EndpointRunRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    client_query_id: Optional[str] = Field(
        default=None, description="Client provided query ID. Can be used to retrieve the status or cancel the query."
    )
    filters_override: Optional[DashboardFilter] = None
    query_override: Optional[dict[str, Any]] = None
    refresh: Optional[RefreshType] = Field(
        default=RefreshType.BLOCKING,
        description=(
            "Whether results should be calculated sync or async, and how much to rely on the cache:\n- `'blocking'` -"
            " calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in"
            " the cache\n- `'async'` - kick off background calculation (returning immediately with a query status),"
            " UNLESS there are very fresh results in the cache\n- `'lazy_async'` - kick off background calculation,"
            " UNLESS there are somewhat fresh results in the cache\n- `'force_blocking'` - calculate synchronously,"
            " even if fresh results are already cached\n- `'force_async'` - kick off background calculation, even if"
            " fresh results are already cached\n- `'force_cache'` - return cached data or a cache miss; always"
            " completes immediately as it never calculates Background calculation can be tracked using the"
            " `query_status` response field."
        ),
    )
    variables_override: Optional[dict[str, dict[str, Any]]] = None
    variables_values: Optional[dict[str, Any]] = None


class ErrorTrackingExternalReference(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    external_url: str
    id: str
    integration: ErrorTrackingExternalReferenceIntegration


class ErrorTrackingIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregations: Optional[ErrorTrackingIssueAggregations] = None
    assignee: Optional[ErrorTrackingIssueAssignee] = None
    cohort: Optional[ErrorTrackingIssueCohort] = None
    description: Optional[str] = None
    external_issues: Optional[list[ErrorTrackingExternalReference]] = None
    first_event: Optional[FirstEvent] = None
    first_seen: datetime
    function: Optional[str] = None
    id: str
    last_event: Optional[LastEvent] = None
    last_seen: datetime
    library: Optional[str] = None
    name: Optional[str] = None
    revenue: Optional[float] = None
    source: Optional[str] = None
    status: Status


class ErrorTrackingRelationalIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignee: Optional[ErrorTrackingIssueAssignee] = None
    cohort: Optional[ErrorTrackingIssueCohort] = None
    description: Optional[str] = None
    external_issues: Optional[list[ErrorTrackingExternalReference]] = None
    first_seen: datetime
    id: str
    name: Optional[str] = None
    status: Status4


class ExperimentBreakdownResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: ExperimentStatsBaseValidated = Field(..., description="Control variant stats for this breakdown")
    breakdown_value: list[Optional[Union[int, str, float, list[Union[int, str, float]]]]] = Field(
        ...,
        description=(
            'The breakdown values as an array (e.g., ["MacOS", "Chrome"] for multi-breakdown, ["Chrome"] for single)'
        ),
    )
    variants: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]] = Field(
        ..., description="Test variant results with statistical comparisons for this breakdown"
    )


class ExperimentEventExposureConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    event: str
    kind: Literal["ExperimentEventExposureConfig"] = "ExperimentEventExposureConfig"
    properties: list[
        Union[
            EventPropertyFilter,
            PersonPropertyFilter,
            ElementPropertyFilter,
            EventMetadataPropertyFilter,
            SessionPropertyFilter,
            CohortPropertyFilter,
            RecordingPropertyFilter,
            LogEntryPropertyFilter,
            GroupPropertyFilter,
            FeaturePropertyFilter,
            FlagPropertyFilter,
            HogQLPropertyFilter,
            EmptyPropertyFilter,
            DataWarehousePropertyFilter,
            DataWarehousePersonPropertyFilter,
            ErrorTrackingIssueFilter,
            LogPropertyFilter,
            RevenueAnalyticsPropertyFilter,
        ]
    ]
    response: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FeatureFlagGroupType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None
    rollout_percentage: Optional[float] = None
    sort_key: Optional[str] = None
    users_affected: Optional[float] = None
    variant: Optional[str] = None


class FunnelCorrelationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: FunnelCorrelationResult
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class HeatMapQuerySource(RootModel[EventsNode]):
    root: EventsNode


class HogQLMetadataResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ch_table_names: Optional[list[str]] = None
    errors: list[HogQLNotice]
    isUsingIndices: Optional[QueryIndexUsage] = None
    isValid: Optional[bool] = None
    notices: list[HogQLNotice]
    query: Optional[str] = None
    table_names: Optional[list[str]] = None
    warnings: list[HogQLNotice]


class InsightActorsQueryBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    includeRecordings: Optional[bool] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class MarketingAnalyticsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    attribution_mode: Optional[AttributionMode] = None
    attribution_window_days: Optional[float] = None
    campaign_name_mappings: Optional[dict[str, dict[str, list[str]]]] = None
    conversion_goals: Optional[list[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]]] = None
    sources_map: Optional[dict[str, SourceMap]] = None


class MaxBillingContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    billing_period: Optional[MaxBillingContextBillingPeriod] = None
    billing_plan: Optional[str] = None
    has_active_subscription: bool
    is_deactivated: Optional[bool] = None
    products: list[MaxProductInfo]
    projected_total_amount_usd: Optional[str] = None
    projected_total_amount_usd_after_discount: Optional[str] = None
    projected_total_amount_usd_with_limit: Optional[str] = None
    projected_total_amount_usd_with_limit_after_discount: Optional[str] = None
    settings: MaxBillingContextSettings
    spend_history: Optional[list[SpendHistoryItem]] = None
    startup_program_label: Optional[str] = None
    startup_program_label_previous: Optional[str] = None
    subscription_level: MaxBillingContextSubscriptionLevel
    total_current_amount_usd: Optional[str] = None
    trial: Optional[MaxBillingContextTrial] = None
    usage_history: Optional[list[UsageHistoryItem]] = None


class MultipleBreakdownOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    values: list[BreakdownItem]


class PlanningMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    steps: list[PlanningStep]
    type: Literal["ai/planning"] = "ai/planning"


class QueryResponseAlternative1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
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
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list[str]] = None


class QueryResponseAlternative4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[list[BreakdownItem]] = None
    breakdowns: Optional[list[MultipleBreakdownOptions]] = None
    compare: Optional[list[CompareItem]] = None
    day: Optional[list[DayItem]] = None
    interval: Optional[list[IntervalItem]] = None
    series: Optional[list[Series]] = None
    status: Optional[list[StatusItem]] = None


class QueryResponseAlternative6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TimelineEntry]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative8(BaseModel):
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
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class QueryResponseAlternative11(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative14(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative15(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[SimilarIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative16(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, Results]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative22(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EmbeddingDistance]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative23(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: Optional[bool] = None


class QueryResponseAlternative24(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None
    usedPreAggregatedTables: Optional[bool] = None


class QueryResponseAlternative25(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative27(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative28(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PageURL]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative30(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative31(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative32(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative33(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative34(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative35(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative36(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative37(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative38(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list[str]] = None


class QueryResponseAlternative39(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: int
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative40(BaseModel):
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
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class QueryResponseAlternative41(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: Optional[bool] = None


class QueryResponseAlternative42(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None
    usedPreAggregatedTables: Optional[bool] = None


class QueryResponseAlternative43(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative45(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative46(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative47(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative48(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative49(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative50(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative51(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative52(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative53(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative55(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative56(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative57(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative61(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative62(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = Field(default=None, description="Wether more breakdown values are available.")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative63(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    isUdf: Optional[bool] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative65(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PathsLink]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative66(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative68(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: FunnelCorrelationResult
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class QueryResponseAlternative70(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative72(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TeamTaxonomyItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative73(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EventTaxonomyItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative74(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative75(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative77(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[VectorSearchResponseItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative78(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[UsageMetric]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RetentionEntity(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    id: Optional[Union[str, float]] = None
    kind: Optional[RetentionEntityKind] = None
    name: Optional[str] = None
    order: Optional[int] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="filters on the event")
    type: Optional[EntityType] = None
    uuid: Optional[str] = None


class RetentionResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_value: Optional[Union[str, float]] = Field(
        default=None, description="Optional breakdown value for retention cohorts"
    )
    date: datetime
    label: str
    values: list[RetentionValue]


class RevenueAnalyticsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: Optional[list[RevenueAnalyticsEventItem]] = []
    filter_test_accounts: Optional[bool] = False
    goals: Optional[list[RevenueAnalyticsGoal]] = []


class SurveyCreationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    appearance: Optional[SurveyAppearanceSchema] = None
    archived: Optional[bool] = None
    conditions: Optional[SurveyDisplayConditionsSchema] = None
    description: str
    enable_partial_responses: Optional[bool] = None
    end_date: Optional[str] = None
    iteration_count: Optional[float] = None
    iteration_frequency_days: Optional[float] = None
    linked_flag_id: Optional[float] = None
    linked_insight_id: Optional[float] = None
    name: str
    questions: list[SurveyQuestionSchema]
    responses_limit: Optional[float] = None
    should_launch: Optional[bool] = None
    start_date: Optional[str] = None
    type: SurveyType


class WebVitalsItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    action: WebVitalsItemAction
    data: list[float]
    days: list[str]


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
            SessionsQueryResponse,
            ErrorTrackingQueryResponse,
            LogsQueryResponse,
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
        SessionsQueryResponse,
        ErrorTrackingQueryResponse,
        LogsQueryResponse,
    ]


class CachedInsightActorsQueryOptionsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[list[BreakdownItem]] = None
    breakdowns: Optional[list[MultipleBreakdownOptions]] = None
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    compare: Optional[list[CompareItem]] = None
    day: Optional[list[DayItem]] = None
    interval: Optional[list[IntervalItem]] = None
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    series: Optional[list[Series]] = None
    status: Optional[list[StatusItem]] = None
    timezone: str


class CustomerAnalyticsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    activity_event: Union[EventsNode, ActionsNode]
    payment_event: Union[EventsNode, ActionsNode]
    signup_event: Union[EventsNode, ActionsNode]
    signup_pageview_event: Union[EventsNode, ActionsNode]
    subscription_event: Union[EventsNode, ActionsNode]


class Response3(BaseModel):
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
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


class Response20(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ErrorTrackingCorrelatedIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignee: Optional[ErrorTrackingIssueAssignee] = None
    cohort: Optional[ErrorTrackingIssueCohort] = None
    description: Optional[str] = None
    event: str
    external_issues: Optional[list[ErrorTrackingExternalReference]] = None
    first_seen: datetime
    id: str
    last_seen: datetime
    library: Optional[str] = None
    name: Optional[str] = None
    odds_ratio: float
    population: Population
    status: Status


class ExperimentExposureCriteria(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exposure_config: Optional[Union[ExperimentEventExposureConfig, ActionsNode]] = None
    filterTestAccounts: Optional[bool] = None
    multiple_variant_handling: Optional[MultipleVariantHandling] = None


class ExperimentHoldoutType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created_at: Optional[str] = None
    created_by: Optional[UserBasicType] = None
    description: Optional[str] = None
    filters: list[FeatureFlagGroupType]
    id: Optional[float] = None
    name: str
    updated_at: Optional[str] = None


class ExperimentRatioMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownFilter: Optional[BreakdownFilter] = None
    conversion_window: Optional[int] = None
    conversion_window_unit: Optional[FunnelConversionWindowTimeUnit] = None
    denominator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    fingerprint: Optional[str] = None
    goal: Optional[ExperimentMetricGoal] = None
    isSharedMetric: Optional[bool] = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    metric_type: Literal["ratio"] = "ratio"
    name: Optional[str] = None
    numerator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    response: Optional[dict[str, Any]] = None
    sharedMetricId: Optional[float] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightActorsQueryOptionsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[list[BreakdownItem]] = None
    breakdowns: Optional[list[MultipleBreakdownOptions]] = None
    compare: Optional[list[CompareItem]] = None
    day: Optional[list[DayItem]] = None
    interval: Optional[list[IntervalItem]] = None
    series: Optional[list[Series]] = None
    status: Optional[list[StatusItem]] = None


class QueryResponseAlternative17(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative64(BaseModel):
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
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RetentionResult]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response21(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response23(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: Optional[TrendsQuery] = None
    credible_intervals: dict[str, list[float]]
    exposure_query: Optional[TrendsQuery] = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantTrendsBaseStats]


class DatabaseSchemaEndpointTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    query: HogQLQuery
    row_count: Optional[float] = None
    status: Optional[str] = None
    type: Literal["endpoint"] = "endpoint"


class DatabaseSchemaManagedViewTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    kind: DatabaseSchemaManagedViewTableKind
    name: str
    query: HogQLQuery
    row_count: Optional[float] = None
    source_id: Optional[str] = None
    type: Literal["managed_view"] = "managed_view"


class DatabaseSchemaMaterializedViewTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    last_run_at: Optional[str] = None
    name: str
    query: HogQLQuery
    row_count: Optional[float] = None
    status: Optional[str] = None
    type: Literal["materialized_view"] = "materialized_view"


class DatabaseSchemaViewTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    query: HogQLQuery
    row_count: Optional[float] = None
    type: Literal["view"] = "view"


class ExperimentFunnelMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownFilter: Optional[BreakdownFilter] = None
    conversion_window: Optional[int] = None
    conversion_window_unit: Optional[FunnelConversionWindowTimeUnit] = None
    fingerprint: Optional[str] = None
    funnel_order_type: Optional[StepOrderValue] = None
    goal: Optional[ExperimentMetricGoal] = None
    isSharedMetric: Optional[bool] = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    metric_type: Literal["funnel"] = "funnel"
    name: Optional[str] = None
    response: Optional[dict[str, Any]] = None
    series: list[Union[EventsNode, ActionsNode]]
    sharedMetricId: Optional[float] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentMeanMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownFilter: Optional[BreakdownFilter] = None
    conversion_window: Optional[int] = None
    conversion_window_unit: Optional[FunnelConversionWindowTimeUnit] = None
    fingerprint: Optional[str] = None
    goal: Optional[ExperimentMetricGoal] = None
    ignore_zeros: Optional[bool] = None
    isSharedMetric: Optional[bool] = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    lower_bound_percentile: Optional[float] = None
    metric_type: Literal["mean"] = "mean"
    name: Optional[str] = None
    response: Optional[dict[str, Any]] = None
    sharedMetricId: Optional[float] = None
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    upper_bound_percentile: Optional[float] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentMetric(RootModel[Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]]):
    root: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]


class InsightsQueryBaseCalendarHeatmapResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
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
                    EventMetadataPropertyFilter,
                    SessionPropertyFilter,
                    CohortPropertyFilter,
                    RecordingPropertyFilter,
                    LogEntryPropertyFilter,
                    GroupPropertyFilter,
                    FeaturePropertyFilter,
                    FlagPropertyFilter,
                    HogQLPropertyFilter,
                    EmptyPropertyFilter,
                    DataWarehousePropertyFilter,
                    DataWarehousePersonPropertyFilter,
                    ErrorTrackingIssueFilter,
                    LogPropertyFilter,
                    RevenueAnalyticsPropertyFilter,
                ]
            ],
            PropertyGroupFilter,
        ]
    ] = Field(default=[], description="Property filters for all series")
    response: Optional[CalendarHeatmapResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class QueryResponseAlternative18(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: Optional[FunnelsQuery] = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class QueryResponseAlternative19(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: Optional[TrendsQuery] = None
    credible_intervals: dict[str, list[float]]
    exposure_query: Optional[TrendsQuery] = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantTrendsBaseStats]


class QueryResponseAlternative20(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: Optional[ExperimentStatsBaseValidated] = None
    breakdown_results: Optional[list[ExperimentBreakdownResult]] = Field(
        default=None,
        description=(
            "Results grouped by breakdown value. When present, baseline and variant_results contain aggregated data."
        ),
    )
    credible_intervals: Optional[dict[str, list[float]]] = None
    insight: Optional[list[dict[str, Any]]] = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Optional[Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]] = None
    p_value: Optional[float] = None
    probability: Optional[dict[str, float]] = None
    significance_code: Optional[ExperimentSignificanceCode] = None
    significant: Optional[bool] = None
    stats_version: Optional[int] = None
    variant_results: Optional[
        Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]
    ] = None
    variants: Optional[Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]] = None


class QueryResponseAlternative59(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: Optional[FunnelsQuery] = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class QueryResponseAlternative60(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: Optional[TrendsQuery] = None
    credible_intervals: dict[str, list[float]]
    exposure_query: Optional[TrendsQuery] = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantTrendsBaseStats]


class NamedArgs(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]


class IsExperimentFunnelMetric(BaseModel):
    namedArgs: Optional[NamedArgs] = None


class IsExperimentMeanMetric(BaseModel):
    namedArgs: Optional[NamedArgs] = None


class IsExperimentRatioMetric(BaseModel):
    namedArgs: Optional[NamedArgs] = None


class Response22(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: Optional[FunnelsQuery] = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class ExperimentMetricTimeseries(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    computed_at: Optional[str] = None
    created_at: str
    errors: Optional[dict[str, str]] = None
    experiment_id: float
    metric_uuid: str
    recalculation_created_at: Optional[str] = None
    recalculation_status: Optional[str] = None
    status: Status5
    timeseries: Optional[dict[str, ExperimentQueryResponse]] = None
    updated_at: str


class QueryResponseAlternative69(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    joins: list[DataWarehouseViewLink]
    tables: dict[
        str,
        Union[
            DatabaseSchemaPostHogTable,
            DatabaseSchemaSystemTable,
            DatabaseSchemaDataWarehouseTable,
            DatabaseSchemaViewTable,
            DatabaseSchemaManagedViewTable,
            DatabaseSchemaBatchExportTable,
            DatabaseSchemaMaterializedViewTable,
            DatabaseSchemaEndpointTable,
        ],
    ]


class QueryResponseAlternative(
    RootModel[
        Union[
            dict[str, Any],
            QueryResponseAlternative1,
            QueryResponseAlternative3,
            QueryResponseAlternative4,
            QueryResponseAlternative5,
            QueryResponseAlternative6,
            QueryResponseAlternative7,
            QueryResponseAlternative8,
            QueryResponseAlternative9,
            QueryResponseAlternative10,
            QueryResponseAlternative11,
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
            QueryResponseAlternative24,
            QueryResponseAlternative25,
            QueryResponseAlternative27,
            QueryResponseAlternative28,
            QueryResponseAlternative29,
            QueryResponseAlternative30,
            QueryResponseAlternative31,
            QueryResponseAlternative32,
            QueryResponseAlternative33,
            QueryResponseAlternative34,
            QueryResponseAlternative35,
            QueryResponseAlternative36,
            Any,
            QueryResponseAlternative37,
            QueryResponseAlternative38,
            QueryResponseAlternative39,
            QueryResponseAlternative40,
            QueryResponseAlternative41,
            QueryResponseAlternative42,
            QueryResponseAlternative43,
            QueryResponseAlternative45,
            QueryResponseAlternative46,
            QueryResponseAlternative47,
            QueryResponseAlternative48,
            QueryResponseAlternative49,
            QueryResponseAlternative50,
            QueryResponseAlternative51,
            QueryResponseAlternative52,
            QueryResponseAlternative53,
            QueryResponseAlternative55,
            QueryResponseAlternative56,
            QueryResponseAlternative57,
            QueryResponseAlternative59,
            QueryResponseAlternative60,
            QueryResponseAlternative61,
            QueryResponseAlternative62,
            QueryResponseAlternative63,
            QueryResponseAlternative64,
            QueryResponseAlternative65,
            QueryResponseAlternative66,
            QueryResponseAlternative68,
            QueryResponseAlternative69,
            QueryResponseAlternative70,
            QueryResponseAlternative71,
            QueryResponseAlternative72,
            QueryResponseAlternative73,
            QueryResponseAlternative74,
            QueryResponseAlternative75,
            QueryResponseAlternative77,
            QueryResponseAlternative78,
        ]
    ]
):
    root: Union[
        dict[str, Any],
        QueryResponseAlternative1,
        QueryResponseAlternative3,
        QueryResponseAlternative4,
        QueryResponseAlternative5,
        QueryResponseAlternative6,
        QueryResponseAlternative7,
        QueryResponseAlternative8,
        QueryResponseAlternative9,
        QueryResponseAlternative10,
        QueryResponseAlternative11,
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
        QueryResponseAlternative24,
        QueryResponseAlternative25,
        QueryResponseAlternative27,
        QueryResponseAlternative28,
        QueryResponseAlternative29,
        QueryResponseAlternative30,
        QueryResponseAlternative31,
        QueryResponseAlternative32,
        QueryResponseAlternative33,
        QueryResponseAlternative34,
        QueryResponseAlternative35,
        QueryResponseAlternative36,
        Any,
        QueryResponseAlternative37,
        QueryResponseAlternative38,
        QueryResponseAlternative39,
        QueryResponseAlternative40,
        QueryResponseAlternative41,
        QueryResponseAlternative42,
        QueryResponseAlternative43,
        QueryResponseAlternative45,
        QueryResponseAlternative46,
        QueryResponseAlternative47,
        QueryResponseAlternative48,
        QueryResponseAlternative49,
        QueryResponseAlternative50,
        QueryResponseAlternative51,
        QueryResponseAlternative52,
        QueryResponseAlternative53,
        QueryResponseAlternative55,
        QueryResponseAlternative56,
        QueryResponseAlternative57,
        QueryResponseAlternative59,
        QueryResponseAlternative60,
        QueryResponseAlternative61,
        QueryResponseAlternative62,
        QueryResponseAlternative63,
        QueryResponseAlternative64,
        QueryResponseAlternative65,
        QueryResponseAlternative66,
        QueryResponseAlternative68,
        QueryResponseAlternative69,
        QueryResponseAlternative70,
        QueryResponseAlternative71,
        QueryResponseAlternative72,
        QueryResponseAlternative73,
        QueryResponseAlternative74,
        QueryResponseAlternative75,
        QueryResponseAlternative77,
        QueryResponseAlternative78,
    ]


class VisualizationItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    answer: Union[
        Union[AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, AssistantHogQLQuery],
        Union[
            TrendsQuery,
            FunnelsQuery,
            RetentionQuery,
            HogQLQuery,
            RevenueAnalyticsGrossRevenueQuery,
            RevenueAnalyticsMetricsQuery,
            RevenueAnalyticsMRRQuery,
            RevenueAnalyticsTopCustomersQuery,
        ],
    ]
    initiator: Optional[str] = None
    plan: Optional[str] = None
    query: Optional[str] = ""


class VisualizationMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    answer: Union[
        Union[AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, AssistantHogQLQuery],
        Union[
            TrendsQuery,
            FunnelsQuery,
            RetentionQuery,
            HogQLQuery,
            RevenueAnalyticsGrossRevenueQuery,
            RevenueAnalyticsMetricsQuery,
            RevenueAnalyticsMRRQuery,
            RevenueAnalyticsTopCustomersQuery,
        ],
    ]
    id: Optional[str] = None
    initiator: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    plan: Optional[str] = None
    query: Optional[str] = ""
    short_id: Optional[str] = None
    type: Literal["ai/viz"] = "ai/viz"


class MultiVisualizationMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    commentary: Optional[str] = None
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    type: Literal["ai/multi_viz"] = "ai/multi_viz"
    visualizations: list[VisualizationItem]


class EndpointRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_age_seconds: Optional[float] = None
    derived_from_insight: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_materialized: Optional[bool] = Field(
        default=None, description="Whether this endpoint's query results are materialized to S3"
    )
    name: Optional[str] = None
    query: Optional[
        Union[HogQLQuery, Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery]]
    ] = None
    sync_frequency: Optional[DataWarehouseSyncInterval] = Field(
        default=None, description="How frequently should the underlying materialized view be updated"
    )


class InsightActorsQueryOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["InsightActorsQueryOptions"] = "InsightActorsQueryOptions"
    response: Optional[InsightActorsQueryOptionsResponse] = None
    source: Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery]
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class HogQLAutocomplete(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    endPosition: int = Field(..., description="End position of the editor word")
    filters: Optional[HogQLFilters] = Field(default=None, description="Table to validate the expression against")
    globals: Optional[dict[str, Any]] = Field(default=None, description="Global values in scope")
    kind: Literal["HogQLAutocomplete"] = "HogQLAutocomplete"
    language: HogLanguage = Field(..., description="Language to validate")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query: str = Field(..., description="Query to validate")
    response: Optional[HogQLAutocompleteResponse] = None
    sourceQuery: Optional[
        Union[
            EventsNode,
            ActionsNode,
            PersonsNode,
            EventsQuery,
            SessionsQuery,
            ActorsQuery,
            GroupsQuery,
            InsightActorsQuery,
            InsightActorsQueryOptions,
            SessionsTimelineQuery,
            HogQuery,
            HogQLQuery,
            HogQLMetadata,
            HogQLAutocomplete,
            RevenueAnalyticsGrossRevenueQuery,
            RevenueAnalyticsMetricsQuery,
            RevenueAnalyticsMRRQuery,
            RevenueAnalyticsOverviewQuery,
            RevenueAnalyticsTopCustomersQuery,
            MarketingAnalyticsTableQuery,
            MarketingAnalyticsAggregatedQuery,
            WebOverviewQuery,
            WebStatsTableQuery,
            WebExternalClicksTableQuery,
            WebGoalsQuery,
            WebVitalsQuery,
            WebVitalsPathBreakdownQuery,
            WebPageURLSearchQuery,
            WebTrendsQuery,
            WebAnalyticsExternalSummaryQuery,
            SessionAttributionExplorerQuery,
            RevenueExampleEventsQuery,
            RevenueExampleDataWarehouseTablesQuery,
            ErrorTrackingQuery,
            ErrorTrackingSimilarIssuesQuery,
            ErrorTrackingBreakdownsQuery,
            ErrorTrackingIssueCorrelationQuery,
            LogsQuery,
            ExperimentFunnelsQuery,
            ExperimentTrendsQuery,
            CalendarHeatmapQuery,
            RecordingsQuery,
            TracesQuery,
            TraceQuery,
            VectorSearchQuery,
            UsageMetricsQuery,
        ]
    ] = Field(default=None, description="Query in whose context to validate.")
    startPosition: int = Field(..., description="Start position of the editor word")
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class HogQLMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    debug: Optional[bool] = Field(
        default=None, description="Enable more verbose output, usually run from the /debug page"
    )
    filters: Optional[HogQLFilters] = Field(default=None, description="Extra filters applied to query via {filters}")
    globals: Optional[dict[str, Any]] = Field(default=None, description="Extra globals for the query")
    kind: Literal["HogQLMetadata"] = "HogQLMetadata"
    language: HogLanguage = Field(..., description="Language to validate")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    query: str = Field(..., description="Query to validate")
    response: Optional[HogQLMetadataResponse] = None
    sourceQuery: Optional[
        Union[
            EventsNode,
            ActionsNode,
            PersonsNode,
            EventsQuery,
            SessionsQuery,
            ActorsQuery,
            GroupsQuery,
            InsightActorsQuery,
            InsightActorsQueryOptions,
            SessionsTimelineQuery,
            HogQuery,
            HogQLQuery,
            HogQLMetadata,
            HogQLAutocomplete,
            RevenueAnalyticsGrossRevenueQuery,
            RevenueAnalyticsMetricsQuery,
            RevenueAnalyticsMRRQuery,
            RevenueAnalyticsOverviewQuery,
            RevenueAnalyticsTopCustomersQuery,
            MarketingAnalyticsTableQuery,
            MarketingAnalyticsAggregatedQuery,
            WebOverviewQuery,
            WebStatsTableQuery,
            WebExternalClicksTableQuery,
            WebGoalsQuery,
            WebVitalsQuery,
            WebVitalsPathBreakdownQuery,
            WebPageURLSearchQuery,
            WebTrendsQuery,
            WebAnalyticsExternalSummaryQuery,
            SessionAttributionExplorerQuery,
            RevenueExampleEventsQuery,
            RevenueExampleDataWarehouseTablesQuery,
            ErrorTrackingQuery,
            ErrorTrackingSimilarIssuesQuery,
            ErrorTrackingBreakdownsQuery,
            ErrorTrackingIssueCorrelationQuery,
            LogsQuery,
            ExperimentFunnelsQuery,
            ExperimentTrendsQuery,
            CalendarHeatmapQuery,
            RecordingsQuery,
            TracesQuery,
            TraceQuery,
            VectorSearchQuery,
            UsageMetricsQuery,
        ]
    ] = Field(
        default=None,
        description='Query within which "expr" and "template" are validated. Defaults to "select * from events"',
    )
    tags: Optional[QueryLogTags] = None
    variables: Optional[dict[str, HogQLVariable]] = Field(
        default=None, description="Variables to be subsituted into the query"
    )
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class HumanMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    type: Literal["human"] = "human"
    ui_context: Optional[MaxUIContext] = None


class MaxDashboardContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Optional[str] = None
    filters: DashboardFilter
    id: float
    insights: list[MaxInsightContext]
    name: Optional[str] = None
    type: Literal["dashboard"] = "dashboard"


class MaxInsightContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Optional[str] = None
    filtersOverride: Optional[DashboardFilter] = None
    id: str
    name: Optional[str] = None
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
        SessionsQuery,
        ActorsQuery,
        GroupsQuery,
        InsightActorsQuery,
        InsightActorsQueryOptions,
        SessionsTimelineQuery,
        HogQuery,
        HogQLQuery,
        HogQLMetadata,
        HogQLAutocomplete,
        HogQLASTQuery,
        SessionAttributionExplorerQuery,
        RevenueExampleEventsQuery,
        RevenueExampleDataWarehouseTablesQuery,
        ErrorTrackingQuery,
        ErrorTrackingSimilarIssuesQuery,
        ErrorTrackingBreakdownsQuery,
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
        DocumentSimilarityQuery,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebExternalClicksTableQuery,
        WebGoalsQuery,
        WebVitalsQuery,
        WebVitalsPathBreakdownQuery,
        WebPageURLSearchQuery,
        WebAnalyticsExternalSummaryQuery,
        RevenueAnalyticsGrossRevenueQuery,
        RevenueAnalyticsMetricsQuery,
        RevenueAnalyticsMRRQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsTopCustomersQuery,
        MarketingAnalyticsTableQuery,
        MarketingAnalyticsAggregatedQuery,
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
        LogsQuery,
        SuggestedQuestionsQuery,
        TeamTaxonomyQuery,
        EventTaxonomyQuery,
        ActorsPropertyTaxonomyQuery,
        TracesQuery,
        TraceQuery,
        VectorSearchQuery,
        UsageMetricsQuery,
    ] = Field(..., discriminator="kind")
    type: Literal["insight"] = "insight"
    variablesOverride: Optional[dict[str, HogQLVariable]] = None


class MaxUIContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions: Optional[list[MaxActionContext]] = None
    dashboards: Optional[list[MaxDashboardContext]] = None
    events: Optional[list[MaxEventContext]] = None
    insights: Optional[list[MaxInsightContext]] = None


class QueryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    async_: Optional[bool] = Field(default=None, alias="async")
    client_query_id: Optional[str] = Field(
        default=None, description="Client provided query ID. Can be used to retrieve the status or cancel the query."
    )
    filters_override: Optional[DashboardFilter] = None
    name: Optional[str] = Field(
        default=None,
        description=(
            "Name given to a query. It's used to identify the query in the UI. Up to 128 characters for a name."
        ),
    )
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
        SessionsQuery,
        ActorsQuery,
        GroupsQuery,
        InsightActorsQuery,
        InsightActorsQueryOptions,
        SessionsTimelineQuery,
        HogQuery,
        HogQLQuery,
        HogQLMetadata,
        HogQLAutocomplete,
        HogQLASTQuery,
        SessionAttributionExplorerQuery,
        RevenueExampleEventsQuery,
        RevenueExampleDataWarehouseTablesQuery,
        ErrorTrackingQuery,
        ErrorTrackingSimilarIssuesQuery,
        ErrorTrackingBreakdownsQuery,
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
        DocumentSimilarityQuery,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebExternalClicksTableQuery,
        WebGoalsQuery,
        WebVitalsQuery,
        WebVitalsPathBreakdownQuery,
        WebPageURLSearchQuery,
        WebAnalyticsExternalSummaryQuery,
        RevenueAnalyticsGrossRevenueQuery,
        RevenueAnalyticsMetricsQuery,
        RevenueAnalyticsMRRQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsTopCustomersQuery,
        MarketingAnalyticsTableQuery,
        MarketingAnalyticsAggregatedQuery,
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
        LogsQuery,
        SuggestedQuestionsQuery,
        TeamTaxonomyQuery,
        EventTaxonomyQuery,
        ActorsPropertyTaxonomyQuery,
        TracesQuery,
        TraceQuery,
        VectorSearchQuery,
        UsageMetricsQuery,
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
    refresh: Optional[RefreshType] = Field(
        default=RefreshType.BLOCKING,
        description=(
            "Whether results should be calculated sync or async, and how much to rely on the cache:\n- `'blocking'` -"
            " calculate synchronously (returning only when the query is done), UNLESS there are very fresh results in"
            " the cache\n- `'async'` - kick off background calculation (returning immediately with a query status),"
            " UNLESS there are very fresh results in the cache\n- `'lazy_async'` - kick off background calculation,"
            " UNLESS there are somewhat fresh results in the cache\n- `'force_blocking'` - calculate synchronously,"
            " even if fresh results are already cached\n- `'force_async'` - kick off background calculation, even if"
            " fresh results are already cached\n- `'force_cache'` - return cached data or a cache miss; always"
            " completes immediately as it never calculates Background calculation can be tracked using the"
            " `query_status` response field."
        ),
    )
    variables_override: Optional[dict[str, dict[str, Any]]] = None


class QueryUpgradeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
        SessionsQuery,
        ActorsQuery,
        GroupsQuery,
        InsightActorsQuery,
        InsightActorsQueryOptions,
        SessionsTimelineQuery,
        HogQuery,
        HogQLQuery,
        HogQLMetadata,
        HogQLAutocomplete,
        HogQLASTQuery,
        SessionAttributionExplorerQuery,
        RevenueExampleEventsQuery,
        RevenueExampleDataWarehouseTablesQuery,
        ErrorTrackingQuery,
        ErrorTrackingSimilarIssuesQuery,
        ErrorTrackingBreakdownsQuery,
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
        DocumentSimilarityQuery,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebExternalClicksTableQuery,
        WebGoalsQuery,
        WebVitalsQuery,
        WebVitalsPathBreakdownQuery,
        WebPageURLSearchQuery,
        WebAnalyticsExternalSummaryQuery,
        RevenueAnalyticsGrossRevenueQuery,
        RevenueAnalyticsMetricsQuery,
        RevenueAnalyticsMRRQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsTopCustomersQuery,
        MarketingAnalyticsTableQuery,
        MarketingAnalyticsAggregatedQuery,
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
        LogsQuery,
        SuggestedQuestionsQuery,
        TeamTaxonomyQuery,
        EventTaxonomyQuery,
        ActorsPropertyTaxonomyQuery,
        TracesQuery,
        TraceQuery,
        VectorSearchQuery,
        UsageMetricsQuery,
    ] = Field(..., discriminator="kind")


class QueryUpgradeResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
        SessionsQuery,
        ActorsQuery,
        GroupsQuery,
        InsightActorsQuery,
        InsightActorsQueryOptions,
        SessionsTimelineQuery,
        HogQuery,
        HogQLQuery,
        HogQLMetadata,
        HogQLAutocomplete,
        HogQLASTQuery,
        SessionAttributionExplorerQuery,
        RevenueExampleEventsQuery,
        RevenueExampleDataWarehouseTablesQuery,
        ErrorTrackingQuery,
        ErrorTrackingSimilarIssuesQuery,
        ErrorTrackingBreakdownsQuery,
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
        DocumentSimilarityQuery,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebExternalClicksTableQuery,
        WebGoalsQuery,
        WebVitalsQuery,
        WebVitalsPathBreakdownQuery,
        WebPageURLSearchQuery,
        WebAnalyticsExternalSummaryQuery,
        RevenueAnalyticsGrossRevenueQuery,
        RevenueAnalyticsMetricsQuery,
        RevenueAnalyticsMRRQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsTopCustomersQuery,
        MarketingAnalyticsTableQuery,
        MarketingAnalyticsAggregatedQuery,
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
        LogsQuery,
        SuggestedQuestionsQuery,
        TeamTaxonomyQuery,
        EventTaxonomyQuery,
        ActorsPropertyTaxonomyQuery,
        TracesQuery,
        TraceQuery,
        VectorSearchQuery,
        UsageMetricsQuery,
    ] = Field(..., discriminator="kind")


class SourceConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    betaSource: Optional[bool] = None
    caption: Optional[Union[str, Any]] = None
    disabledReason: Optional[str] = None
    docsUrl: Optional[str] = None
    existingSource: Optional[bool] = None
    featureFlag: Optional[str] = None
    fields: list[
        Union[
            SourceFieldInputConfig,
            SourceFieldSwitchGroupConfig,
            SourceFieldSelectConfig,
            SourceFieldOauthConfig,
            SourceFieldFileUploadConfig,
            SourceFieldSSHTunnelConfig,
        ]
    ]
    iconClassName: Optional[str] = None
    iconPath: str
    label: Optional[str] = None
    name: ExternalDataSourceType
    suggestedTables: Optional[list[SuggestedTable]] = Field(
        default=[], description="Tables to suggest enabling, with optional tooltip explaining why"
    )
    unreleasedSource: Optional[bool] = None


class Option(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: Optional[
        list[
            Union[
                SourceFieldInputConfig,
                SourceFieldSwitchGroupConfig,
                SourceFieldSelectConfig,
                SourceFieldOauthConfig,
                SourceFieldFileUploadConfig,
                SourceFieldSSHTunnelConfig,
            ]
        ]
    ] = None
    label: str
    value: str


class SourceFieldSelectConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    converter: Optional[SourceFieldSelectConfigConverter] = None
    defaultValue: str
    label: str
    name: str
    options: list[Option]
    required: bool
    type: Literal["select"] = "select"


class SourceFieldSwitchGroupConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    caption: Optional[str] = None
    default: Union[str, float, bool]
    fields: list[
        Union[
            SourceFieldInputConfig,
            SourceFieldSwitchGroupConfig,
            SourceFieldSelectConfig,
            SourceFieldOauthConfig,
            SourceFieldFileUploadConfig,
            SourceFieldSSHTunnelConfig,
        ]
    ]
    label: str
    name: str
    type: Literal["switch-group"] = "switch-group"
