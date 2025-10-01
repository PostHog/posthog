# mypy: disable-error-code="assignment"

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Literal, Union

from posthog.schema_models import SchemaModel

SchemaRoot = Any


class AIEventType(StrEnum):
    FIELD_AI_GENERATION = "$ai_generation"
    FIELD_AI_EMBEDDING = "$ai_embedding"
    FIELD_AI_SPAN = "$ai_span"
    FIELD_AI_TRACE = "$ai_trace"
    FIELD_AI_METRIC = "$ai_metric"
    FIELD_AI_FEEDBACK = "$ai_feedback"


class MathGroupTypeIndex(float, Enum):
    NUMBER_0 = 0
    NUMBER_1 = 1
    NUMBER_2 = 2
    NUMBER_3 = 3
    NUMBER_4 = 4


class AggregationAxisFormat(StrEnum):
    NUMERIC = "numeric"
    DURATION = "duration"
    DURATION_MS = "duration_ms"
    PERCENTAGE = "percentage"
    PERCENTAGE_SCALED = "percentage_scaled"
    CURRENCY = "currency"


class AlertCalculationInterval(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AlertConditionType(StrEnum):
    ABSOLUTE_VALUE = "absolute_value"
    RELATIVE_INCREASE = "relative_increase"
    RELATIVE_DECREASE = "relative_decrease"


class AlertState(StrEnum):
    FIRING = "Firing"
    NOT_FIRING = "Not firing"
    ERRORED = "Errored"
    SNOOZED = "Snoozed"


class AssistantArrayPropertyFilterOperator(StrEnum):
    EXACT = "exact"
    IS_NOT = "is_not"


@dataclass
class AssistantBaseMultipleBreakdownFilter(SchemaModel):
    property: str


class AssistantContextualTool(StrEnum):
    SEARCH_SESSION_RECORDINGS = "search_session_recordings"
    GENERATE_HOGQL_QUERY = "generate_hogql_query"
    FIX_HOGQL_QUERY = "fix_hogql_query"
    ANALYZE_USER_INTERVIEWS = "analyze_user_interviews"
    CREATE_AND_QUERY_INSIGHT = "create_and_query_insight"
    CREATE_HOG_TRANSFORMATION_FUNCTION = "create_hog_transformation_function"
    CREATE_HOG_FUNCTION_FILTERS = "create_hog_function_filters"
    CREATE_HOG_FUNCTION_INPUTS = "create_hog_function_inputs"
    CREATE_MESSAGE_TEMPLATE = "create_message_template"
    NAVIGATE = "navigate"
    FILTER_ERROR_TRACKING_ISSUES = "filter_error_tracking_issues"
    FIND_ERROR_TRACKING_IMPACTFUL_ISSUE_EVENT_LIST = "find_error_tracking_impactful_issue_event_list"
    EXPERIMENT_RESULTS_SUMMARY = "experiment_results_summary"
    CREATE_SURVEY = "create_survey"
    ANALYZE_SURVEY_RESPONSES = "analyze_survey_responses"
    SEARCH_DOCS = "search_docs"
    SEARCH_INSIGHTS = "search_insights"
    SESSION_SUMMARIZATION = "session_summarization"
    CREATE_DASHBOARD = "create_dashboard"
    FILTER_REVENUE_ANALYTICS = "filter_revenue_analytics"


@dataclass
class AssistantDateRange(SchemaModel):
    date_from: str
    date_to: str | None = None


class AssistantDateTimePropertyFilterOperator(StrEnum):
    IS_DATE_EXACT = "is_date_exact"
    IS_DATE_BEFORE = "is_date_before"
    IS_DATE_AFTER = "is_date_after"


@dataclass
class AssistantDurationRange(SchemaModel):
    date_from: str


class AssistantEventMultipleBreakdownFilterType(StrEnum):
    COHORT = "cohort"
    PERSON = "person"
    EVENT = "event"
    EVENT_METADATA = "event_metadata"
    SESSION = "session"
    HOGQL = "hogql"
    REVENUE_ANALYTICS = "revenue_analytics"


class AssistantEventType(StrEnum):
    STATUS = "status"
    MESSAGE = "message"
    CONVERSATION = "conversation"
    NOTEBOOK = "notebook"


@dataclass
class AssistantFormOption(SchemaModel):
    value: str
    variant: str | None = None


class AssistantFunnelsBreakdownType(StrEnum):
    PERSON = "person"
    EVENT = "event"
    GROUP = "group"
    SESSION = "session"


class FunnelAggregateByHogQL(Enum):
    PROPERTIES__SESSION_ID = "properties.$session_id"
    NONE_TYPE_NONE = None


class AssistantFunnelsMath(StrEnum):
    FIRST_TIME_FOR_USER = "first_time_for_user"
    FIRST_TIME_FOR_USER_WITH_FILTERS = "first_time_for_user_with_filters"


class AssistantGenerationStatusType(StrEnum):
    ACK = "ack"
    GENERATION_ERROR = "generation_error"


@dataclass
class AssistantGenericMultipleBreakdownFilter(SchemaModel):
    property: str
    type: AssistantEventMultipleBreakdownFilterType


class AssistantGenericPropertyFilterType(StrEnum):
    EVENT = "event"
    PERSON = "person"
    SESSION = "session"
    FEATURE = "feature"


@dataclass
class AssistantHogQLQuery(SchemaModel):
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    query: str


class AssistantMessageType(StrEnum):
    HUMAN = "human"
    TOOL = "tool"
    AI = "ai"
    AI_REASONING = "ai/reasoning"
    AI_VIZ = "ai/viz"
    AI_MULTI_VIZ = "ai/multi_viz"
    AI_FAILURE = "ai/failure"
    AI_NOTEBOOK = "ai/notebook"
    AI_PLANNING = "ai/planning"
    AI_TASK_EXECUTION = "ai/task_execution"


class AssistantNavigateUrls(StrEnum):
    ACTIONS = "actions"
    ACTIVITY = "activity"
    ALERTS = "alerts"
    ANNOTATIONS = "annotations"
    CREATE_ACTION = "createAction"
    COHORTS = "cohorts"
    DASHBOARDS = "dashboards"
    DATABASE = "database"
    EARLY_ACCESS_FEATURES = "earlyAccessFeatures"
    EVENT_DEFINITIONS = "eventDefinitions"
    ERROR_TRACKING = "errorTracking"
    EXPERIMENTS = "experiments"
    FEATURE_FLAGS = "featureFlags"
    GAME368HEDGEHOGS = "game368hedgehogs"
    HEATMAPS = "heatmaps"
    INGESTION_WARNINGS = "ingestionWarnings"
    INSIGHTS = "insights"
    INSIGHT_NEW = "insightNew"
    PIPELINE = "pipeline"
    PROJECT_HOMEPAGE = "projectHomepage"
    PROPERTY_DEFINITIONS = "propertyDefinitions"
    MAX = "max"
    NOTEBOOKS = "notebooks"
    REPLAY = "replay"
    REPLAY_SETTINGS = "replaySettings"
    REVENUE_ANALYTICS = "revenueAnalytics"
    SAVED_INSIGHTS = "savedInsights"
    SETTINGS = "settings"
    SQL_EDITOR = "sqlEditor"
    SURVEYS = "surveys"
    SURVEY_TEMPLATES = "surveyTemplates"
    TOOLBAR_LAUNCH = "toolbarLaunch"
    WEB_ANALYTICS = "webAnalytics"
    WEB_ANALYTICS_WEB_VITALS = "webAnalyticsWebVitals"
    PERSONS = "persons"


class AssistantNumericValuePropertyFilterOperator(StrEnum):
    EXACT = "exact"
    GT = "gt"
    LT = "lt"


class MeanRetentionCalculation(StrEnum):
    SIMPLE = "simple"
    WEIGHTED = "weighted"
    NONE = "none"


class RetentionReference(StrEnum):
    TOTAL = "total"
    PREVIOUS = "previous"


class AssistantSetPropertyFilterOperator(StrEnum):
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"


class AssistantStringOrBooleanValuePropertyFilterOperator(StrEnum):
    EXACT = "exact"
    IS_NOT = "is_not"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"
    REGEX = "regex"
    NOT_REGEX = "not_regex"


@dataclass
class AssistantToolCall(SchemaModel):
    args: dict[str, Any]
    id: str
    name: str
    type: Literal["tool_call"] = "tool_call"


@dataclass
class AssistantToolCallMessage(SchemaModel):
    content: str
    tool_call_id: str
    type: Literal["tool"] = "tool"
    id: str | None = None
    ui_payload: dict[str, Any] | None = None
    visible: bool | None = None


AssistantTrendsDisplayType = Union[str, Any]


class Display(StrEnum):
    ACTIONS_LINE_GRAPH = "ActionsLineGraph"
    ACTIONS_BAR = "ActionsBar"
    ACTIONS_UNSTACKED_BAR = "ActionsUnstackedBar"
    ACTIONS_AREA_GRAPH = "ActionsAreaGraph"
    ACTIONS_LINE_GRAPH_CUMULATIVE = "ActionsLineGraphCumulative"
    BOLD_NUMBER = "BoldNumber"
    ACTIONS_PIE = "ActionsPie"
    ACTIONS_BAR_VALUE = "ActionsBarValue"
    ACTIONS_TABLE = "ActionsTable"
    WORLD_MAP = "WorldMap"
    CALENDAR_HEATMAP = "CalendarHeatmap"


class YAxisScaleType(StrEnum):
    LOG10 = "log10"
    LINEAR = "linear"


@dataclass
class AssistantTrendsFilter(SchemaModel):
    aggregationAxisFormat: AggregationAxisFormat | None = AggregationAxisFormat.NUMERIC
    aggregationAxisPostfix: str | None = None
    aggregationAxisPrefix: str | None = None
    decimalPlaces: float | None = None
    display: Display | None = Display.ACTIONS_LINE_GRAPH
    formulas: list[str] | None = None
    showLegend: bool | None = False
    showPercentStackView: bool | None = False
    showValuesOnSeries: bool | None = False
    yAxisScaleType: YAxisScaleType | None = YAxisScaleType.LINEAR


class AutocompleteCompletionItemKind(StrEnum):
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


@dataclass
class BaseAssistantMessage(SchemaModel):
    id: str | None = None


class BaseMathType(StrEnum):
    TOTAL = "total"
    DAU = "dau"
    WEEKLY_ACTIVE = "weekly_active"
    MONTHLY_ACTIVE = "monthly_active"
    UNIQUE_SESSION = "unique_session"
    FIRST_TIME_FOR_USER = "first_time_for_user"
    FIRST_MATCHING_EVENT_FOR_USER = "first_matching_event_for_user"


class BillingSpendResponseBreakdownType(StrEnum):
    TYPE = "type"
    TEAM = "team"
    MULTIPLE = "multiple"


class BillingUsageResponseBreakdownType(StrEnum):
    TYPE = "type"
    TEAM = "team"
    MULTIPLE = "multiple"


class BreakdownAttributionType(StrEnum):
    FIRST_TOUCH = "first_touch"
    LAST_TOUCH = "last_touch"
    ALL_EVENTS = "all_events"
    STEP = "step"


class BreakdownType(StrEnum):
    COHORT = "cohort"
    PERSON = "person"
    EVENT = "event"
    EVENT_METADATA = "event_metadata"
    GROUP = "group"
    SESSION = "session"
    HOGQL = "hogql"
    DATA_WAREHOUSE = "data_warehouse"
    DATA_WAREHOUSE_PERSON_PROPERTY = "data_warehouse_person_property"
    REVENUE_ANALYTICS = "revenue_analytics"


@dataclass
class CompareItem(SchemaModel):
    label: str
    value: str


@dataclass
class StatusItem(SchemaModel):
    label: str
    value: str


@dataclass
class CalendarHeatmapFilter(SchemaModel):
    dummy: str | None = None


class CalendarHeatmapMathType(StrEnum):
    TOTAL = "total"
    DAU = "dau"


class ChartDisplayCategory(StrEnum):
    TIME_SERIES = "TimeSeries"
    CUMULATIVE_TIME_SERIES = "CumulativeTimeSeries"
    TOTAL_VALUE = "TotalValue"


class ChartDisplayType(StrEnum):
    ACTIONS_LINE_GRAPH = "ActionsLineGraph"
    ACTIONS_BAR = "ActionsBar"
    ACTIONS_UNSTACKED_BAR = "ActionsUnstackedBar"
    ACTIONS_STACKED_BAR = "ActionsStackedBar"
    ACTIONS_AREA_GRAPH = "ActionsAreaGraph"
    ACTIONS_LINE_GRAPH_CUMULATIVE = "ActionsLineGraphCumulative"
    BOLD_NUMBER = "BoldNumber"
    ACTIONS_PIE = "ActionsPie"
    ACTIONS_BAR_VALUE = "ActionsBarValue"
    ACTIONS_TABLE = "ActionsTable"
    WORLD_MAP = "WorldMap"
    CALENDAR_HEATMAP = "CalendarHeatmap"


class DisplayType(StrEnum):
    AUTO = "auto"
    LINE = "line"
    BAR = "bar"


class YAxisPosition(StrEnum):
    LEFT = "left"
    RIGHT = "right"


@dataclass
class ChartSettingsDisplay(SchemaModel):
    color: str | None = None
    displayType: DisplayType | None = None
    label: str | None = None
    trendLine: bool | None = None
    yAxisPosition: YAxisPosition | None = None


class Style(StrEnum):
    NONE = "none"
    NUMBER = "number"
    PERCENT = "percent"


@dataclass
class ChartSettingsFormatting(SchemaModel):
    decimalPlaces: float | None = None
    prefix: str | None = None
    style: Style | None = None
    suffix: str | None = None


@dataclass
class CompareFilter(SchemaModel):
    compare: bool | None = False
    compare_to: str | None = None


class ColorMode(StrEnum):
    LIGHT = "light"
    DARK = "dark"


@dataclass
class ConditionalFormattingRule(SchemaModel):
    bytecode: list
    color: str
    columnName: str
    id: str
    input: str
    templateId: str
    colorMode: ColorMode | None = None


class CountPerActorMathType(StrEnum):
    AVG_COUNT_PER_ACTOR = "avg_count_per_actor"
    MIN_COUNT_PER_ACTOR = "min_count_per_actor"
    MAX_COUNT_PER_ACTOR = "max_count_per_actor"
    MEDIAN_COUNT_PER_ACTOR = "median_count_per_actor"
    P75_COUNT_PER_ACTOR = "p75_count_per_actor"
    P90_COUNT_PER_ACTOR = "p90_count_per_actor"
    P95_COUNT_PER_ACTOR = "p95_count_per_actor"
    P99_COUNT_PER_ACTOR = "p99_count_per_actor"


class CurrencyCode(StrEnum):
    AED = "AED"
    AFN = "AFN"
    ALL = "ALL"
    AMD = "AMD"
    ANG = "ANG"
    AOA = "AOA"
    ARS = "ARS"
    AUD = "AUD"
    AWG = "AWG"
    AZN = "AZN"
    BAM = "BAM"
    BBD = "BBD"
    BDT = "BDT"
    BGN = "BGN"
    BHD = "BHD"
    BIF = "BIF"
    BMD = "BMD"
    BND = "BND"
    BOB = "BOB"
    BRL = "BRL"
    BSD = "BSD"
    BTC = "BTC"
    BTN = "BTN"
    BWP = "BWP"
    BYN = "BYN"
    BZD = "BZD"
    CAD = "CAD"
    CDF = "CDF"
    CHF = "CHF"
    CLP = "CLP"
    CNY = "CNY"
    COP = "COP"
    CRC = "CRC"
    CVE = "CVE"
    CZK = "CZK"
    DJF = "DJF"
    DKK = "DKK"
    DOP = "DOP"
    DZD = "DZD"
    EGP = "EGP"
    ERN = "ERN"
    ETB = "ETB"
    EUR = "EUR"
    FJD = "FJD"
    GBP = "GBP"
    GEL = "GEL"
    GHS = "GHS"
    GIP = "GIP"
    GMD = "GMD"
    GNF = "GNF"
    GTQ = "GTQ"
    GYD = "GYD"
    HKD = "HKD"
    HNL = "HNL"
    HRK = "HRK"
    HTG = "HTG"
    HUF = "HUF"
    IDR = "IDR"
    ILS = "ILS"
    INR = "INR"
    IQD = "IQD"
    IRR = "IRR"
    ISK = "ISK"
    JMD = "JMD"
    JOD = "JOD"
    JPY = "JPY"
    KES = "KES"
    KGS = "KGS"
    KHR = "KHR"
    KMF = "KMF"
    KRW = "KRW"
    KWD = "KWD"
    KYD = "KYD"
    KZT = "KZT"
    LAK = "LAK"
    LBP = "LBP"
    LKR = "LKR"
    LRD = "LRD"
    LTL = "LTL"
    LVL = "LVL"
    LSL = "LSL"
    LYD = "LYD"
    MAD = "MAD"
    MDL = "MDL"
    MGA = "MGA"
    MKD = "MKD"
    MMK = "MMK"
    MNT = "MNT"
    MOP = "MOP"
    MRU = "MRU"
    MTL = "MTL"
    MUR = "MUR"
    MVR = "MVR"
    MWK = "MWK"
    MXN = "MXN"
    MYR = "MYR"
    MZN = "MZN"
    NAD = "NAD"
    NGN = "NGN"
    NIO = "NIO"
    NOK = "NOK"
    NPR = "NPR"
    NZD = "NZD"
    OMR = "OMR"
    PAB = "PAB"
    PEN = "PEN"
    PGK = "PGK"
    PHP = "PHP"
    PKR = "PKR"
    PLN = "PLN"
    PYG = "PYG"
    QAR = "QAR"
    RON = "RON"
    RSD = "RSD"
    RUB = "RUB"
    RWF = "RWF"
    SAR = "SAR"
    SBD = "SBD"
    SCR = "SCR"
    SDG = "SDG"
    SEK = "SEK"
    SGD = "SGD"
    SRD = "SRD"
    SSP = "SSP"
    STN = "STN"
    SYP = "SYP"
    SZL = "SZL"
    THB = "THB"
    TJS = "TJS"
    TMT = "TMT"
    TND = "TND"
    TOP = "TOP"
    TRY_ = "TRY"
    TTD = "TTD"
    TWD = "TWD"
    TZS = "TZS"
    UAH = "UAH"
    UGX = "UGX"
    USD = "USD"
    UYU = "UYU"
    UZS = "UZS"
    VES = "VES"
    VND = "VND"
    VUV = "VUV"
    WST = "WST"
    XAF = "XAF"
    XCD = "XCD"
    XOF = "XOF"
    XPF = "XPF"
    YER = "YER"
    ZAR = "ZAR"
    ZMW = "ZMW"


class CustomChannelField(StrEnum):
    UTM_SOURCE = "utm_source"
    UTM_MEDIUM = "utm_medium"
    UTM_CAMPAIGN = "utm_campaign"
    REFERRING_DOMAIN = "referring_domain"
    URL = "url"
    PATHNAME = "pathname"
    HOSTNAME = "hostname"


class CustomChannelOperator(StrEnum):
    EXACT = "exact"
    IS_NOT = "is_not"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"
    REGEX = "regex"
    NOT_REGEX = "not_regex"


@dataclass
class CustomEventConversionGoal(SchemaModel):
    customEventName: str


class DataColorToken(StrEnum):
    PRESET_1 = "preset-1"
    PRESET_2 = "preset-2"
    PRESET_3 = "preset-3"
    PRESET_4 = "preset-4"
    PRESET_5 = "preset-5"
    PRESET_6 = "preset-6"
    PRESET_7 = "preset-7"
    PRESET_8 = "preset-8"
    PRESET_9 = "preset-9"
    PRESET_10 = "preset-10"
    PRESET_11 = "preset-11"
    PRESET_12 = "preset-12"
    PRESET_13 = "preset-13"
    PRESET_14 = "preset-14"
    PRESET_15 = "preset-15"


class DataTableNodeViewPropsContextType(StrEnum):
    EVENT_DEFINITION = "event_definition"
    TEAM_COLUMNS = "team_columns"


@dataclass
class DataWarehouseEventsModifier(SchemaModel):
    distinct_id_field: str
    id_field: str
    table_name: str
    timestamp_field: str


@dataclass
class DataWarehouseViewLinkConfiguration(SchemaModel):
    experiments_optimized: bool | None = None
    experiments_timestamp_key: str | None = None


class DatabaseSchemaManagedViewTableKind(StrEnum):
    REVENUE_ANALYTICS_CHARGE = "revenue_analytics_charge"
    REVENUE_ANALYTICS_CUSTOMER = "revenue_analytics_customer"
    REVENUE_ANALYTICS_PRODUCT = "revenue_analytics_product"
    REVENUE_ANALYTICS_REVENUE_ITEM = "revenue_analytics_revenue_item"
    REVENUE_ANALYTICS_SUBSCRIPTION = "revenue_analytics_subscription"


@dataclass
class DatabaseSchemaSchema(SchemaModel):
    id: str
    incremental: bool
    name: str
    should_sync: bool
    last_synced_at: str | None = None
    status: str | None = None


@dataclass
class DatabaseSchemaSource(SchemaModel):
    id: str
    prefix: str
    source_type: str
    status: str
    last_synced_at: str | None = None


class DatabaseSchemaTableType(StrEnum):
    POSTHOG = "posthog"
    SYSTEM = "system"
    DATA_WAREHOUSE = "data_warehouse"
    VIEW = "view"
    BATCH_EXPORT = "batch_export"
    MATERIALIZED_VIEW = "materialized_view"
    MANAGED_VIEW = "managed_view"


class DatabaseSerializedFieldType(StrEnum):
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
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
    MATERIALIZED_VIEW = "materialized_view"
    UNKNOWN = "unknown"


@dataclass
class DateRange(SchemaModel):
    date_from: str | None = None
    date_to: str | None = None
    explicitDate: bool | None = False


DatetimeDay = str


class DeepResearchType(StrEnum):
    PLANNING = "planning"
    REPORT = "report"


class DefaultChannelTypes(StrEnum):
    CROSS_NETWORK = "Cross Network"
    PAID_SEARCH = "Paid Search"
    PAID_SOCIAL = "Paid Social"
    PAID_VIDEO = "Paid Video"
    PAID_SHOPPING = "Paid Shopping"
    PAID_UNKNOWN = "Paid Unknown"
    DIRECT = "Direct"
    ORGANIC_SEARCH = "Organic Search"
    ORGANIC_SOCIAL = "Organic Social"
    ORGANIC_VIDEO = "Organic Video"
    ORGANIC_SHOPPING = "Organic Shopping"
    PUSH = "Push"
    SMS = "SMS"
    AUDIO = "Audio"
    EMAIL = "Email"
    REFERRAL = "Referral"
    AFFILIATE = "Affiliate"
    UNKNOWN = "Unknown"


class DurationType(StrEnum):
    DURATION = "duration"
    ACTIVE_SECONDS = "active_seconds"
    INACTIVE_SECONDS = "inactive_seconds"


class Key(StrEnum):
    TAG_NAME = "tag_name"
    TEXT = "text"
    HREF = "href"
    SELECTOR = "selector"


@dataclass
class ElementType(SchemaModel):
    attributes: dict[str, str]
    tag_name: str
    attr_class: list[str] | None = None
    attr_id: str | None = None
    href: str | None = None
    nth_child: float | None = None
    nth_of_type: float | None = None
    order: float | None = None
    text: str | None = None


@dataclass
class EmptyPropertyFilter(SchemaModel):
    pass


class EntityType(StrEnum):
    ACTIONS = "actions"
    EVENTS = "events"
    DATA_WAREHOUSE = "data_warehouse"
    NEW_ENTITY = "new_entity"


@dataclass
class Population(SchemaModel):
    both: float
    exception_only: float
    neither: float
    success_only: float


class Status(StrEnum):
    ARCHIVED = "archived"
    ACTIVE = "active"
    RESOLVED = "resolved"
    PENDING_RELEASE = "pending_release"
    SUPPRESSED = "suppressed"


@dataclass
class FirstEvent(SchemaModel):
    properties: str
    timestamp: str
    uuid: str


@dataclass
class LastEvent(SchemaModel):
    properties: str
    timestamp: str
    uuid: str


@dataclass
class VolumeBucket(SchemaModel):
    label: str
    value: float


@dataclass
class ErrorTrackingIssueAggregations(SchemaModel):
    occurrences: float
    sessions: float
    users: float
    volume_buckets: list[VolumeBucket]
    volumeRange: list[float] | None = None


class ErrorTrackingIssueAssigneeType(StrEnum):
    USER = "user"
    ROLE = "role"


class OrderBy(StrEnum):
    LAST_SEEN = "last_seen"
    FIRST_SEEN = "first_seen"
    OCCURRENCES = "occurrences"
    USERS = "users"
    SESSIONS = "sessions"


class OrderDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class Status2(StrEnum):
    ARCHIVED = "archived"
    ACTIVE = "active"
    RESOLVED = "resolved"
    PENDING_RELEASE = "pending_release"
    SUPPRESSED = "suppressed"
    ALL = "all"


@dataclass
class ErrorTrackingIssueImpactToolOutput(SchemaModel):
    events: list[str]


class Status4(StrEnum):
    ARCHIVED = "archived"
    ACTIVE = "active"
    RESOLVED = "resolved"
    PENDING_RELEASE = "pending_release"
    SUPPRESSED = "suppressed"


@dataclass
class EventDefinition(SchemaModel):
    elements: list
    event: str
    properties: dict[str, Any]


class CorrelationType(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass
class Person(SchemaModel):
    distinct_ids: list[str]
    properties: dict[str, Any]
    is_identified: bool | None = None


@dataclass
class EventType(SchemaModel):
    distinct_id: str
    elements: list[ElementType]
    event: str
    id: str
    properties: dict[str, Any]
    timestamp: str
    elements_chain: str | None = None
    person: Person | None = None
    uuid: str | None = None


@dataclass
class Properties(SchemaModel):
    email: str | None = None
    name: str | None = None


@dataclass
class EventsQueryPersonColumn(SchemaModel):
    created_at: str
    distinct_id: str
    properties: Properties
    uuid: str


class MultipleVariantHandling(StrEnum):
    EXCLUDE = "exclude"
    FIRST_SEEN = "first_seen"


@dataclass
class ExperimentExposureTimeSeries(SchemaModel):
    days: list[str]
    exposure_counts: list[float]
    variant: str


class ExperimentMetricGoal(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"


class ExperimentMetricMathType(StrEnum):
    TOTAL = "total"
    SUM = "sum"
    UNIQUE_SESSION = "unique_session"
    MIN = "min"
    MAX = "max"
    AVG = "avg"
    DAU = "dau"
    UNIQUE_GROUP = "unique_group"
    HOGQL = "hogql"


@dataclass
class ExperimentMetricOutlierHandling(SchemaModel):
    ignore_zeros: bool | None = None
    lower_bound_percentile: float | None = None
    upper_bound_percentile: float | None = None


class Status5(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ExperimentMetricType(StrEnum):
    FUNNEL = "funnel"
    MEAN = "mean"
    RATIO = "ratio"


class ExperimentSignificanceCode(StrEnum):
    SIGNIFICANT = "significant"
    NOT_ENOUGH_EXPOSURE = "not_enough_exposure"
    LOW_WIN_PROBABILITY = "low_win_probability"
    HIGH_LOSS = "high_loss"
    HIGH_P_VALUE = "high_p_value"


class ExperimentStatsValidationFailure(StrEnum):
    NOT_ENOUGH_EXPOSURES = "not-enough-exposures"
    BASELINE_MEAN_IS_ZERO = "baseline-mean-is-zero"
    NOT_ENOUGH_METRIC_DATA = "not-enough-metric-data"


@dataclass
class ExperimentVariantFunnelsBaseStats(SchemaModel):
    failure_count: float
    key: str
    success_count: float


@dataclass
class ExperimentVariantTrendsBaseStats(SchemaModel):
    absolute_exposure: float
    count: float
    exposure: float
    key: str


class ExternalDataSourceType(StrEnum):
    STRIPE = "Stripe"
    HUBSPOT = "Hubspot"
    POSTGRES = "Postgres"
    MY_SQL = "MySQL"
    MSSQL = "MSSQL"
    ZENDESK = "Zendesk"
    SNOWFLAKE = "Snowflake"
    SALESFORCE = "Salesforce"
    VITALLY = "Vitally"
    BIG_QUERY = "BigQuery"
    CHARGEBEE = "Chargebee"
    REVENUE_CAT = "RevenueCat"
    POLAR = "Polar"
    GOOGLE_ADS = "GoogleAds"
    META_ADS = "MetaAds"
    KLAVIYO = "Klaviyo"
    MAILCHIMP = "Mailchimp"
    BRAZE = "Braze"
    MAILJET = "Mailjet"
    REDSHIFT = "Redshift"
    GOOGLE_SHEETS = "GoogleSheets"
    MONGO_DB = "MongoDB"
    TEMPORAL_IO = "TemporalIO"
    DO_IT = "DoIt"
    LINKEDIN_ADS = "LinkedinAds"
    REDDIT_ADS = "RedditAds"


class ExternalQueryErrorCode(StrEnum):
    PLATFORM_ACCESS_REQUIRED = "platform_access_required"
    QUERY_EXECUTION_FAILED = "query_execution_failed"


class ExternalQueryStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class FailureMessage(SchemaModel):
    type: Literal["ai/failure"] = "ai/failure"
    content: str | None = None
    id: str | None = None


@dataclass
class FileSystemCount(SchemaModel):
    count: float


class Tag(StrEnum):
    ALPHA = "alpha"
    BETA = "beta"


@dataclass
class FileSystemEntry(SchemaModel):
    id: str
    path: str
    field_loading: bool | None = None
    created_at: str | None = None
    href: str | None = None
    meta: dict[str, Any] | None = None
    ref: str | None = None
    shortcut: bool | None = None
    tags: list[Tag] | None = None
    type: str | None = None
    visualOrder: float | None = None


class FileSystemIconType(StrEnum):
    DASHBOARD = "dashboard"
    LLM_ANALYTICS = "llm_analytics"
    PRODUCT_ANALYTICS = "product_analytics"
    REVENUE_ANALYTICS = "revenue_analytics"
    REVENUE_ANALYTICS_METADATA = "revenue_analytics_metadata"
    MARKETING_SETTINGS = "marketing_settings"
    EMBEDDED_ANALYTICS = "embedded_analytics"
    SQL_EDITOR = "sql_editor"
    WEB_ANALYTICS = "web_analytics"
    ERROR_TRACKING = "error_tracking"
    HEATMAP = "heatmap"
    SESSION_REPLAY = "session_replay"
    SURVEY = "survey"
    USER_INTERVIEW = "user_interview"
    EARLY_ACCESS_FEATURE = "early_access_feature"
    EXPERIMENT = "experiment"
    FEATURE_FLAG = "feature_flag"
    DATA_PIPELINE = "data_pipeline"
    DATA_PIPELINE_METADATA = "data_pipeline_metadata"
    DATA_WAREHOUSE = "data_warehouse"
    TASK = "task"
    LINK = "link"
    LOGS = "logs"
    MESSAGING = "messaging"
    NOTEBOOK = "notebook"
    ACTION = "action"
    COMMENT = "comment"
    ANNOTATION = "annotation"
    EVENT_DEFINITION = "event_definition"
    PROPERTY_DEFINITION = "property_definition"
    INGESTION_WARNING = "ingestion_warning"
    PERSON = "person"
    COHORT = "cohort"
    GROUP = "group"
    INSIGHT_FUNNELS = "insight/funnels"
    INSIGHT_TRENDS = "insight/trends"
    INSIGHT_RETENTION = "insight/retention"
    INSIGHT_PATHS = "insight/paths"
    INSIGHT_LIFECYCLE = "insight/lifecycle"
    INSIGHT_STICKINESS = "insight/stickiness"
    INSIGHT_HOG = "insight/hog"
    TEAM_ACTIVITY = "team_activity"
    HOME = "home"


@dataclass
class FileSystemImport(SchemaModel):
    path: str
    field_loading: bool | None = None
    category: str | None = None
    created_at: str | None = None
    flag: str | None = None
    href: str | None = None
    iconColor: list[str] | None = None
    iconType: FileSystemIconType | None = None
    id: str | None = None
    meta: dict[str, Any] | None = None
    protocol: str | None = None
    ref: str | None = None
    shortcut: bool | None = None
    tags: list[Tag] | None = None
    type: str | None = None
    visualOrder: float | None = None


class FilterLogicalOperator(StrEnum):
    AND_ = "AND"
    OR_ = "OR"


@dataclass
class FlagPropertyFilter(SchemaModel):
    key: str
    operator: Literal["flag_evaluates_to"] = "flag_evaluates_to"
    type: Literal["flag"] = "flag"
    value: Union[bool, str]
    label: str | None = None


class FunnelConversionWindowTimeUnit(StrEnum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class FunnelCorrelationResultsType(StrEnum):
    EVENTS = "events"
    PROPERTIES = "properties"
    EVENT_WITH_PROPERTIES = "event_with_properties"


@dataclass
class FunnelExclusionLegacy(SchemaModel):
    funnel_from_step: float
    funnel_to_step: float
    custom_name: str | None = None
    id: Union[str, float] | None = None
    index: float | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    order: float | None = None
    type: EntityType | None = None


class FunnelLayout(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class FunnelMathType(StrEnum):
    TOTAL = "total"
    FIRST_TIME_FOR_USER = "first_time_for_user"
    FIRST_TIME_FOR_USER_WITH_FILTERS = "first_time_for_user_with_filters"


class FunnelPathType(StrEnum):
    FUNNEL_PATH_BEFORE_STEP = "funnel_path_before_step"
    FUNNEL_PATH_BETWEEN_STEPS = "funnel_path_between_steps"
    FUNNEL_PATH_AFTER_STEP = "funnel_path_after_step"


class FunnelStepReference(StrEnum):
    TOTAL = "total"
    PREVIOUS = "previous"


FunnelStepsBreakdownResults = list[list[dict[str, Any]]]


FunnelStepsResults = list[dict[str, Any]]


@dataclass
class FunnelTimeToConvertResults(SchemaModel):
    average_conversion_time: float | None
    bins: list[list[int]]


FunnelTrendsResults = list[dict[str, Any]]


class FunnelVizType(StrEnum):
    STEPS = "steps"
    TIME_TO_CONVERT = "time_to_convert"
    TRENDS = "trends"


@dataclass
class GoalLine(SchemaModel):
    label: str
    value: float
    borderColor: str | None = None
    displayIfCrossed: bool | None = None
    displayLabel: bool | None = None


class HedgehogColorOptions(StrEnum):
    GREEN = "green"
    RED = "red"
    BLUE = "blue"
    PURPLE = "purple"
    DARK = "dark"
    LIGHT = "light"
    SEPIA = "sepia"
    INVERT = "invert"
    INVERT_HUE = "invert-hue"
    GREYSCALE = "greyscale"


@dataclass
class HogCompileResponse(SchemaModel):
    bytecode: list
    locals: list


class HogLanguage(StrEnum):
    HOG = "hog"
    HOG_JSON = "hogJson"
    HOG_QL = "hogQL"
    HOG_QL_EXPR = "hogQLExpr"
    HOG_TEMPLATE = "hogTemplate"


class BounceRatePageViewMode(StrEnum):
    COUNT_PAGEVIEWS = "count_pageviews"
    UNIQ_URLS = "uniq_urls"
    UNIQ_PAGE_SCREEN_AUTOCAPTURES = "uniq_page_screen_autocaptures"


class InCohortVia(StrEnum):
    AUTO = "auto"
    LEFTJOIN = "leftjoin"
    SUBQUERY = "subquery"
    LEFTJOIN_CONJOINED = "leftjoin_conjoined"


class MaterializationMode(StrEnum):
    AUTO = "auto"
    LEGACY_NULL_AS_STRING = "legacy_null_as_string"
    LEGACY_NULL_AS_NULL = "legacy_null_as_null"
    DISABLED = "disabled"


class PersonsArgMaxVersion(StrEnum):
    AUTO = "auto"
    V1 = "v1"
    V2 = "v2"


class PersonsJoinMode(StrEnum):
    INNER = "inner"
    LEFT = "left"


class PersonsOnEventsMode(StrEnum):
    DISABLED = "disabled"
    PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS = "person_id_no_override_properties_on_events"
    PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS = "person_id_override_properties_on_events"
    PERSON_ID_OVERRIDE_PROPERTIES_JOINED = "person_id_override_properties_joined"


class PropertyGroupsMode(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    OPTIMIZED = "optimized"


class SessionTableVersion(StrEnum):
    AUTO = "auto"
    V1 = "v1"
    V2 = "v2"
    V3 = "v3"


class SessionsV2JoinMode(StrEnum):
    STRING = "string"
    UUID = "uuid"


@dataclass
class HogQLVariable(SchemaModel):
    code_name: str
    variableId: str
    isNull: bool | None = None
    value: Any | None = None


@dataclass
class HogQueryResponse(SchemaModel):
    results: Any
    bytecode: list | None = None
    coloredBytecode: list | None = None
    stdout: str | None = None


class InfinityValue(float, Enum):
    NUMBER_999999 = 999999
    NUMBER__999999 = -999999


class Compare(StrEnum):
    CURRENT = "current"
    PREVIOUS = "previous"


class InsightFilterProperty(StrEnum):
    TRENDS_FILTER = "trendsFilter"
    FUNNELS_FILTER = "funnelsFilter"
    RETENTION_FILTER = "retentionFilter"
    PATHS_FILTER = "pathsFilter"
    STICKINESS_FILTER = "stickinessFilter"
    CALENDAR_HEATMAP_FILTER = "calendarHeatmapFilter"
    LIFECYCLE_FILTER = "lifecycleFilter"


class InsightNodeKind(StrEnum):
    TRENDS_QUERY = "TrendsQuery"
    FUNNELS_QUERY = "FunnelsQuery"
    RETENTION_QUERY = "RetentionQuery"
    PATHS_QUERY = "PathsQuery"
    STICKINESS_QUERY = "StickinessQuery"
    LIFECYCLE_QUERY = "LifecycleQuery"


class InsightThresholdType(StrEnum):
    ABSOLUTE = "absolute"
    PERCENTAGE = "percentage"


@dataclass
class InsightsThresholdBounds(SchemaModel):
    lower: float | None = None
    upper: float | None = None


class IntegrationKind(StrEnum):
    SLACK = "slack"
    SALESFORCE = "salesforce"
    HUBSPOT = "hubspot"
    GOOGLE_PUBSUB = "google-pubsub"
    GOOGLE_CLOUD_STORAGE = "google-cloud-storage"
    GOOGLE_ADS = "google-ads"
    GOOGLE_SHEETS = "google-sheets"
    LINKEDIN_ADS = "linkedin-ads"
    SNAPCHAT = "snapchat"
    INTERCOM = "intercom"
    EMAIL = "email"
    TWILIO = "twilio"
    LINEAR = "linear"
    GITHUB = "github"
    META_ADS = "meta-ads"
    CLICKUP = "clickup"
    REDDIT_ADS = "reddit-ads"


class IntervalType(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass
class LLMTraceEvent(SchemaModel):
    createdAt: str
    event: Union[AIEventType, str]
    id: str
    properties: dict[str, Any]


@dataclass
class LLMTracePerson(SchemaModel):
    created_at: str
    distinct_id: str
    properties: dict[str, Any]
    uuid: str


class LifecycleToggle(StrEnum):
    NEW = "new"
    RESURRECTING = "resurrecting"
    RETURNING = "returning"
    DORMANT = "dormant"


class LogSeverityLevel(StrEnum):
    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    FATAL = "fatal"


class OrderBy2(StrEnum):
    LATEST = "latest"
    EARLIEST = "earliest"


class MarketingAnalyticsBaseColumns(StrEnum):
    CAMPAIGN = "Campaign"
    SOURCE = "Source"
    COST = "Cost"
    CLICKS = "Clicks"
    IMPRESSIONS = "Impressions"
    CPC = "CPC"
    CTR = "CTR"
    REPORTED_CONVERSION = "Reported Conversion"


class MarketingAnalyticsColumnsSchemaNames(StrEnum):
    CAMPAIGN = "campaign"
    CLICKS = "clicks"
    COST = "cost"
    CURRENCY = "currency"
    DATE = "date"
    IMPRESSIONS = "impressions"
    SOURCE = "source"
    REPORTED_CONVERSION = "reported_conversion"


class MarketingAnalyticsHelperForColumnNames(StrEnum):
    GOAL = "Goal"
    COST_PER = "Cost per"


class MarketingAnalyticsOrderByEnum(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class MarketingAnalyticsSchemaFieldTypes(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    FLOAT = "float"
    DATETIME = "datetime"
    DATE = "date"
    BOOLEAN = "boolean"


@dataclass
class MatchedRecordingEvent(SchemaModel):
    uuid: str


@dataclass
class MaxActionContext(SchemaModel):
    id: float
    name: str
    type: Literal["action"] = "action"
    description: str | None = None


@dataclass
class MaxAddonInfo(SchemaModel):
    current_usage: float
    description: str
    has_exceeded_limit: bool
    is_used: bool
    name: str
    type: str
    docs_url: str | None = None
    percentage_usage: float | None = None
    projected_amount_usd: str | None = None
    projected_amount_usd_with_limit: str | None = None
    usage_limit: float | None = None


@dataclass
class SpendHistoryItem(SchemaModel):
    breakdown_type: BillingSpendResponseBreakdownType | None
    breakdown_value: Union[str, list[str]] | None
    data: list[float]
    dates: list[str]
    id: float
    label: str


@dataclass
class UsageHistoryItem(SchemaModel):
    breakdown_type: BillingUsageResponseBreakdownType | None
    breakdown_value: Union[str, list[str]] | None
    data: list[float]
    dates: list[str]
    id: float
    label: str


class MaxBillingContextBillingPeriodInterval(StrEnum):
    MONTH = "month"
    YEAR = "year"


@dataclass
class MaxBillingContextSettings(SchemaModel):
    active_destinations: float
    autocapture_on: bool


class MaxBillingContextSubscriptionLevel(StrEnum):
    FREE = "free"
    PAID = "paid"
    CUSTOM = "custom"


@dataclass
class MaxBillingContextTrial(SchemaModel):
    is_active: bool
    expires_at: str | None = None
    target: str | None = None


@dataclass
class MaxEventContext(SchemaModel):
    id: str
    type: Literal["event"] = "event"
    description: str | None = None
    name: str | None = None


@dataclass
class MaxProductInfo(SchemaModel):
    addons: list[MaxAddonInfo]
    description: str
    has_exceeded_limit: bool
    is_used: bool
    name: str
    percentage_usage: float
    type: str
    current_usage: float | None = None
    custom_limit_usd: float | None = None
    docs_url: str | None = None
    next_period_custom_limit_usd: float | None = None
    projected_amount_usd: str | None = None
    projected_amount_usd_with_limit: str | None = None
    usage_limit: float | None = None


@dataclass
class MinimalHedgehogConfig(SchemaModel):
    accessories: list[str]
    color: HedgehogColorOptions | None
    use_as_profile: bool


class MultipleBreakdownType(StrEnum):
    COHORT = "cohort"
    PERSON = "person"
    EVENT = "event"
    EVENT_METADATA = "event_metadata"
    GROUP = "group"
    SESSION = "session"
    HOGQL = "hogql"
    REVENUE_ANALYTICS = "revenue_analytics"


@dataclass
class NamedQueryLastExecutionTimesRequest(SchemaModel):
    names: list[str]


class NodeKind(StrEnum):
    EVENTS_NODE = "EventsNode"
    ACTIONS_NODE = "ActionsNode"
    DATA_WAREHOUSE_NODE = "DataWarehouseNode"
    EVENTS_QUERY = "EventsQuery"
    PERSONS_NODE = "PersonsNode"
    HOG_QUERY = "HogQuery"
    HOG_QL_QUERY = "HogQLQuery"
    HOG_QLAST_QUERY = "HogQLASTQuery"
    HOG_QL_METADATA = "HogQLMetadata"
    HOG_QL_AUTOCOMPLETE = "HogQLAutocomplete"
    ACTORS_QUERY = "ActorsQuery"
    GROUPS_QUERY = "GroupsQuery"
    FUNNELS_ACTORS_QUERY = "FunnelsActorsQuery"
    FUNNEL_CORRELATION_ACTORS_QUERY = "FunnelCorrelationActorsQuery"
    SESSIONS_TIMELINE_QUERY = "SessionsTimelineQuery"
    RECORDINGS_QUERY = "RecordingsQuery"
    SESSION_ATTRIBUTION_EXPLORER_QUERY = "SessionAttributionExplorerQuery"
    REVENUE_EXAMPLE_EVENTS_QUERY = "RevenueExampleEventsQuery"
    REVENUE_EXAMPLE_DATA_WAREHOUSE_TABLES_QUERY = "RevenueExampleDataWarehouseTablesQuery"
    ERROR_TRACKING_QUERY = "ErrorTrackingQuery"
    ERROR_TRACKING_ISSUE_CORRELATION_QUERY = "ErrorTrackingIssueCorrelationQuery"
    LOGS_QUERY = "LogsQuery"
    SESSION_BATCH_EVENTS_QUERY = "SessionBatchEventsQuery"
    DATA_TABLE_NODE = "DataTableNode"
    DATA_VISUALIZATION_NODE = "DataVisualizationNode"
    SAVED_INSIGHT_NODE = "SavedInsightNode"
    INSIGHT_VIZ_NODE = "InsightVizNode"
    TRENDS_QUERY = "TrendsQuery"
    CALENDAR_HEATMAP_QUERY = "CalendarHeatmapQuery"
    FUNNELS_QUERY = "FunnelsQuery"
    RETENTION_QUERY = "RetentionQuery"
    PATHS_QUERY = "PathsQuery"
    STICKINESS_QUERY = "StickinessQuery"
    STICKINESS_ACTORS_QUERY = "StickinessActorsQuery"
    LIFECYCLE_QUERY = "LifecycleQuery"
    INSIGHT_ACTORS_QUERY = "InsightActorsQuery"
    INSIGHT_ACTORS_QUERY_OPTIONS = "InsightActorsQueryOptions"
    FUNNEL_CORRELATION_QUERY = "FunnelCorrelationQuery"
    WEB_OVERVIEW_QUERY = "WebOverviewQuery"
    WEB_STATS_TABLE_QUERY = "WebStatsTableQuery"
    WEB_EXTERNAL_CLICKS_TABLE_QUERY = "WebExternalClicksTableQuery"
    WEB_GOALS_QUERY = "WebGoalsQuery"
    WEB_VITALS_QUERY = "WebVitalsQuery"
    WEB_VITALS_PATH_BREAKDOWN_QUERY = "WebVitalsPathBreakdownQuery"
    WEB_PAGE_URL_SEARCH_QUERY = "WebPageURLSearchQuery"
    WEB_TRENDS_QUERY = "WebTrendsQuery"
    WEB_ANALYTICS_EXTERNAL_SUMMARY_QUERY = "WebAnalyticsExternalSummaryQuery"
    REVENUE_ANALYTICS_GROSS_REVENUE_QUERY = "RevenueAnalyticsGrossRevenueQuery"
    REVENUE_ANALYTICS_METRICS_QUERY = "RevenueAnalyticsMetricsQuery"
    REVENUE_ANALYTICS_MRR_QUERY = "RevenueAnalyticsMRRQuery"
    REVENUE_ANALYTICS_OVERVIEW_QUERY = "RevenueAnalyticsOverviewQuery"
    REVENUE_ANALYTICS_TOP_CUSTOMERS_QUERY = "RevenueAnalyticsTopCustomersQuery"
    MARKETING_ANALYTICS_TABLE_QUERY = "MarketingAnalyticsTableQuery"
    EXPERIMENT_METRIC = "ExperimentMetric"
    EXPERIMENT_QUERY = "ExperimentQuery"
    EXPERIMENT_EXPOSURE_QUERY = "ExperimentExposureQuery"
    EXPERIMENT_EVENT_EXPOSURE_CONFIG = "ExperimentEventExposureConfig"
    EXPERIMENT_TRENDS_QUERY = "ExperimentTrendsQuery"
    EXPERIMENT_FUNNELS_QUERY = "ExperimentFunnelsQuery"
    EXPERIMENT_DATA_WAREHOUSE_NODE = "ExperimentDataWarehouseNode"
    DATABASE_SCHEMA_QUERY = "DatabaseSchemaQuery"
    SUGGESTED_QUESTIONS_QUERY = "SuggestedQuestionsQuery"
    TEAM_TAXONOMY_QUERY = "TeamTaxonomyQuery"
    EVENT_TAXONOMY_QUERY = "EventTaxonomyQuery"
    ACTORS_PROPERTY_TAXONOMY_QUERY = "ActorsPropertyTaxonomyQuery"
    TRACES_QUERY = "TracesQuery"
    TRACE_QUERY = "TraceQuery"
    VECTOR_SEARCH_QUERY = "VectorSearchQuery"


@dataclass
class PageURL(SchemaModel):
    count: float
    url: str


@dataclass
class PathCleaningFilter(SchemaModel):
    alias: str | None = None
    order: float | None = None
    regex: str | None = None


class PathType(StrEnum):
    FIELD_PAGEVIEW = "$pageview"
    FIELD_SCREEN = "$screen"
    CUSTOM_EVENT = "custom_event"
    HOGQL = "hogql"


@dataclass
class PathsFilterLegacy(SchemaModel):
    edge_limit: int | None = None
    end_point: str | None = None
    exclude_events: list[str] | None = None
    funnel_filter: dict[str, Any] | None = None
    funnel_paths: FunnelPathType | None = None
    include_event_types: list[PathType] | None = None
    local_path_cleaning_filters: list[PathCleaningFilter] | None = None
    max_edge_weight: int | None = None
    min_edge_weight: int | None = None
    path_groupings: list[str] | None = None
    path_replacements: bool | None = None
    path_type: PathType | None = None
    paths_hogql_expression: str | None = None
    start_point: str | None = None
    step_limit: int | None = None


@dataclass
class PathsLink(SchemaModel):
    average_conversion_time: float
    source: str
    target: str
    value: float


@dataclass
class PersistedFolder(SchemaModel):
    created_at: str
    id: str
    path: str
    protocol: str
    type: str
    updated_at: str


@dataclass
class PersonType(SchemaModel):
    distinct_ids: list[str]
    properties: dict[str, Any]
    created_at: str | None = None
    id: str | None = None
    is_identified: bool | None = None
    name: str | None = None
    uuid: str | None = None


class PlanningStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class PlaywrightWorkspaceSetupData(SchemaModel):
    organization_name: str | None = None


@dataclass
class PlaywrightWorkspaceSetupResult(SchemaModel):
    organization_id: str
    organization_name: str
    personal_api_key: str
    team_id: str
    team_name: str
    user_email: str
    user_id: str


class PropertyFilterType(StrEnum):
    META = "meta"
    EVENT = "event"
    EVENT_METADATA = "event_metadata"
    PERSON = "person"
    ELEMENT = "element"
    FEATURE = "feature"
    SESSION = "session"
    COHORT = "cohort"
    RECORDING = "recording"
    LOG_ENTRY = "log_entry"
    GROUP = "group"
    HOGQL = "hogql"
    DATA_WAREHOUSE = "data_warehouse"
    DATA_WAREHOUSE_PERSON_PROPERTY = "data_warehouse_person_property"
    ERROR_TRACKING_ISSUE = "error_tracking_issue"
    REVENUE_ANALYTICS = "revenue_analytics"
    FLAG = "flag"
    LOG = "log"


class PropertyMathType(StrEnum):
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    P75 = "p75"
    P90 = "p90"
    P95 = "p95"
    P99 = "p99"


class PropertyOperator(StrEnum):
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
    IN_ = "in"
    NOT_IN = "not_in"
    IS_CLEANED_PATH_EXACT = "is_cleaned_path_exact"
    FLAG_EVALUATES_TO = "flag_evaluates_to"


@dataclass
class Mark(SchemaModel):
    type: str
    attrs: dict[str, Any] | None = None


@dataclass
class ProsemirrorJSONContent(SchemaModel):
    attrs: dict[str, Any] | None = None
    content: list[ProsemirrorJSONContent] | None = None
    marks: list[Mark] | None = None
    text: str | None = None
    type: str | None = None


class QueryIndexUsage(StrEnum):
    UNDECISIVE = "undecisive"
    NO = "no"
    PARTIAL = "partial"
    YES = "yes"


@dataclass
class QueryLogTags(SchemaModel):
    productKey: str | None = None
    scene: str | None = None


@dataclass
class QueryResponseAlternative6(SchemaModel):
    results: Any
    bytecode: list | None = None
    coloredBytecode: list | None = None
    stdout: str | None = None


@dataclass
class QueryResponseAlternative18(SchemaModel):
    date_range: DateRange
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    timeseries: list[ExperimentExposureTimeSeries]
    total_exposures: dict[str, float]


@dataclass
class QueryResponseAlternative64(SchemaModel):
    questions: list[str]


@dataclass
class QueryTiming(SchemaModel):
    k: str
    t: float


@dataclass
class ReasoningMessage(SchemaModel):
    content: str
    type: Literal["ai/reasoning"] = "ai/reasoning"
    id: str | None = None
    substeps: list[str] | None = None


@dataclass
class RecordingDurationFilter(SchemaModel):
    key: DurationType
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    value: float
    label: str | None = None


class RecordingOrder(StrEnum):
    DURATION = "duration"
    RECORDING_DURATION = "recording_duration"
    INACTIVE_SECONDS = "inactive_seconds"
    ACTIVE_SECONDS = "active_seconds"
    START_TIME = "start_time"
    CONSOLE_ERROR_COUNT = "console_error_count"
    CLICK_COUNT = "click_count"
    KEYPRESS_COUNT = "keypress_count"
    MOUSE_ACTIVITY_COUNT = "mouse_activity_count"
    ACTIVITY_SCORE = "activity_score"


class RecordingOrderDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


@dataclass
class RecordingPropertyFilter(SchemaModel):
    key: Union[DurationType, str]
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class RefreshType(StrEnum):
    ASYNC_ = "async"
    ASYNC_EXCEPT_ON_CACHE_MISS = "async_except_on_cache_miss"
    BLOCKING = "blocking"
    FORCE_ASYNC = "force_async"
    FORCE_BLOCKING = "force_blocking"
    FORCE_CACHE = "force_cache"
    LAZY_ASYNC = "lazy_async"


@dataclass
class ResolvedDateRangeResponse(SchemaModel):
    date_from: str
    date_to: str


@dataclass
class ResultCustomizationBase(SchemaModel):
    color: DataColorToken | None = None
    hidden: bool | None = None


class ResultCustomizationBy(StrEnum):
    VALUE = "value"
    POSITION = "position"


@dataclass
class ResultCustomizationByPosition(SchemaModel):
    assignmentBy: Literal["position"] = "position"
    color: DataColorToken | None = None
    hidden: bool | None = None


@dataclass
class ResultCustomizationByValue(SchemaModel):
    assignmentBy: Literal["value"] = "value"
    color: DataColorToken | None = None
    hidden: bool | None = None


class RetentionDashboardDisplayType(StrEnum):
    TABLE_ONLY = "table_only"
    GRAPH_ONLY = "graph_only"
    ALL = "all"


class RetentionEntityKind(StrEnum):
    ACTIONS_NODE = "ActionsNode"
    EVENTS_NODE = "EventsNode"


class RetentionPeriod(StrEnum):
    HOUR = "Hour"
    DAY = "Day"
    WEEK = "Week"
    MONTH = "Month"


class RetentionType(StrEnum):
    RETENTION_RECURRING = "retention_recurring"
    RETENTION_FIRST_TIME = "retention_first_time"
    RETENTION_FIRST_EVER_OCCURRENCE = "retention_first_ever_occurrence"


@dataclass
class RevenueAnalyticsBreakdown(SchemaModel):
    property: str
    type: Literal["revenue_analytics"] = "revenue_analytics"


class MrrOrGross(StrEnum):
    MRR = "mrr"
    GROSS = "gross"


@dataclass
class RevenueAnalyticsGoal(SchemaModel):
    due_date: str
    goal: float
    name: str
    mrr_or_gross: MrrOrGross | None = MrrOrGross.GROSS


@dataclass
class RevenueAnalyticsMRRQueryResultItem(SchemaModel):
    churn: Any
    contraction: Any
    expansion: Any
    new: Any
    total: Any


class RevenueAnalyticsOverviewItemKey(StrEnum):
    REVENUE = "revenue"
    PAYING_CUSTOMER_COUNT = "paying_customer_count"
    AVG_REVENUE_PER_CUSTOMER = "avg_revenue_per_customer"


@dataclass
class RevenueAnalyticsPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["revenue_analytics"] = "revenue_analytics"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class RevenueAnalyticsTopCustomersGroupBy(StrEnum):
    MONTH = "month"
    ALL = "all"


@dataclass
class RevenueCurrencyPropertyConfig(SchemaModel):
    property: str | None = None
    static: CurrencyCode | None = None


@dataclass
class RootAssistantMessage1(SchemaModel):
    content: str
    tool_call_id: str
    type: Literal["tool"] = "tool"
    id: str | None = None
    ui_payload: dict[str, Any] | None = None
    visible: bool | None = None


@dataclass
class SamplingRate(SchemaModel):
    numerator: float
    denominator: float | None = None


class SessionAttributionGroupBy(StrEnum):
    CHANNEL_TYPE = "ChannelType"
    MEDIUM = "Medium"
    SOURCE = "Source"
    CAMPAIGN = "Campaign"
    AD_IDS = "AdIds"
    REFERRING_DOMAIN = "ReferringDomain"
    INITIAL_URL = "InitialURL"


@dataclass
class SessionData(SchemaModel):
    event_uuid: str
    person_id: str
    session_id: str


@dataclass
class SessionEventsItem(SchemaModel):
    events: list[list]
    session_id: str


@dataclass
class SessionPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["session"] = "session"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class SnapshotSource(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    UNKNOWN = "unknown"


class Storage(StrEnum):
    OBJECT_STORAGE_LTS = "object_storage_lts"
    OBJECT_STORAGE = "object_storage"


@dataclass
class SharingConfigurationSettings(SchemaModel):
    detailed: bool | None = None
    hideExtraDetails: bool | None = None
    legend: bool | None = None
    noHeader: bool | None = None
    showInspector: bool | None = None
    whitelabel: bool | None = None


class SimpleIntervalType(StrEnum):
    DAY = "day"
    MONTH = "month"


@dataclass
class SourceFieldFileUploadJsonFormatConfig(SchemaModel):
    format: Literal[".json"] = ".json"
    keys: Union[str, list[str]]


class SourceFieldInputConfigType(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    SEARCH = "search"
    URL = "url"
    PASSWORD = "password"
    TIME = "time"
    NUMBER = "number"
    TEXTAREA = "textarea"


@dataclass
class SourceFieldOauthConfig(SchemaModel):
    kind: str
    label: str
    name: str
    required: bool
    type: Literal["oauth"] = "oauth"


@dataclass
class SourceFieldSSHTunnelConfig(SchemaModel):
    label: str
    name: str
    type: Literal["ssh-tunnel"] = "ssh-tunnel"


class SourceFieldSelectConfigConverter(StrEnum):
    STR_TO_INT = "str_to_int"
    STR_TO_BOOL = "str_to_bool"
    STR_TO_OPTIONAL_INT = "str_to_optional_int"


@dataclass
class SourceMap(SchemaModel):
    campaign: str | None = None
    clicks: str | None = None
    cost: str | None = None
    currency: str | None = None
    date: str | None = None
    impressions: str | None = None
    reported_conversion: str | None = None
    source: str | None = None


class StepOrderValue(StrEnum):
    STRICT = "strict"
    UNORDERED = "unordered"
    ORDERED = "ordered"


class StickinessComputationMode(StrEnum):
    NON_CUMULATIVE = "non_cumulative"
    CUMULATIVE = "cumulative"


@dataclass
class StickinessFilterLegacy(SchemaModel):
    compare: bool | None = None
    compare_to: str | None = None
    display: ChartDisplayType | None = None
    hidden_legend_keys: dict[str, Union[bool, Any]] | None = None
    show_legend: bool | None = None
    show_multiple_y_axes: bool | None = None
    show_values_on_series: bool | None = None


class StickinessOperator(StrEnum):
    GTE = "gte"
    LTE = "lte"
    EXACT = "exact"


class SubscriptionDropoffMode(StrEnum):
    LAST_EVENT = "last_event"
    AFTER_DROPOFF_PERIOD = "after_dropoff_period"


@dataclass
class SuggestedQuestionsQueryResponse(SchemaModel):
    questions: list[str]


@dataclass
class SurveyAnalysisResponseItem(SchemaModel):
    isOpenEnded: bool | None = True
    responseText: str | None = ""
    timestamp: str | None = ""


@dataclass
class Value(SchemaModel):
    id: float
    name: str


@dataclass
class Actions(SchemaModel):
    values: list[Value]


class SurveyMatchType(StrEnum):
    EXACT = "exact"
    IS_NOT = "is_not"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"
    REGEX = "regex"
    NOT_REGEX = "not_regex"


class SurveyPosition(StrEnum):
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    MIDDLE_LEFT = "middle_left"
    MIDDLE_CENTER = "middle_center"
    MIDDLE_RIGHT = "middle_right"
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    NEXT_TO_TRIGGER = "next_to_trigger"


class SurveyQuestionBranchingType(StrEnum):
    NEXT_QUESTION = "next_question"
    END = "end"
    RESPONSE_BASED = "response_based"
    SPECIFIC_QUESTION = "specific_question"


class SurveyQuestionDescriptionContentType(StrEnum):
    HTML = "html"
    TEXT = "text"


@dataclass
class Branching(SchemaModel):
    type: SurveyQuestionBranchingType
    index: float | None = None
    responseValues: dict[str, Union[str, float]] | None = None


class Display1(StrEnum):
    NUMBER = "number"
    EMOJI = "emoji"


class SurveyQuestionType(StrEnum):
    OPEN = "open"
    MULTIPLE_CHOICE = "multiple_choice"
    SINGLE_CHOICE = "single_choice"
    RATING = "rating"
    LINK = "link"


class SurveyType(StrEnum):
    POPOVER = "popover"
    WIDGET = "widget"
    FULL_SCREEN = "full_screen"
    API = "api"
    EXTERNAL_SURVEY = "external_survey"


class SurveyWidgetType(StrEnum):
    BUTTON = "button"
    TAB = "tab"
    SELECTOR = "selector"


class TaskExecutionStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaxonomicFilterGroupType(StrEnum):
    METADATA = "metadata"
    ACTIONS = "actions"
    COHORTS = "cohorts"
    COHORTS_WITH_ALL = "cohorts_with_all"
    DATA_WAREHOUSE = "data_warehouse"
    DATA_WAREHOUSE_PROPERTIES = "data_warehouse_properties"
    DATA_WAREHOUSE_PERSON_PROPERTIES = "data_warehouse_person_properties"
    ELEMENTS = "elements"
    EVENTS = "events"
    EVENT_PROPERTIES = "event_properties"
    EVENT_FEATURE_FLAGS = "event_feature_flags"
    EVENT_METADATA = "event_metadata"
    NUMERICAL_EVENT_PROPERTIES = "numerical_event_properties"
    PERSON_PROPERTIES = "person_properties"
    PAGEVIEW_URLS = "pageview_urls"
    SCREENS = "screens"
    CUSTOM_EVENTS = "custom_events"
    WILDCARD = "wildcard"
    GROUPS = "groups"
    PERSONS = "persons"
    FEATURE_FLAGS = "feature_flags"
    INSIGHTS = "insights"
    EXPERIMENTS = "experiments"
    PLUGINS = "plugins"
    DASHBOARDS = "dashboards"
    NAME_GROUPS = "name_groups"
    SESSION_PROPERTIES = "session_properties"
    HOGQL_EXPRESSION = "hogql_expression"
    NOTEBOOKS = "notebooks"
    LOG_ENTRIES = "log_entries"
    ERROR_TRACKING_ISSUES = "error_tracking_issues"
    LOG_ATTRIBUTES = "log_attributes"
    REPLAY = "replay"
    REVENUE_ANALYTICS_PROPERTIES = "revenue_analytics_properties"
    RESOURCES = "resources"
    ERROR_TRACKING_PROPERTIES = "error_tracking_properties"
    MAX_AI_CONTEXT = "max_ai_context"


@dataclass
class TestSetupRequest(SchemaModel):
    data: dict[str, Any] | None = None


@dataclass
class TestSetupResponse(SchemaModel):
    success: bool
    test_name: str
    available_tests: list[str] | None = None
    error: str | None = None
    result: Any | None = None


@dataclass
class TimelineEntry(SchemaModel):
    events: list[EventType]
    recording_duration_s: float | None = None
    sessionId: str | None = None


class DetailedResultsAggregationType(StrEnum):
    TOTAL = "total"
    AVERAGE = "average"
    MEDIAN = "median"


@dataclass
class TrendsFilterLegacy(SchemaModel):
    aggregation_axis_format: AggregationAxisFormat | None = None
    aggregation_axis_postfix: str | None = None
    aggregation_axis_prefix: str | None = None
    breakdown_histogram_bin_count: float | None = None
    compare: bool | None = None
    compare_to: str | None = None
    decimal_places: float | None = None
    display: ChartDisplayType | None = None
    formula: str | None = None
    hidden_legend_keys: dict[str, Union[bool, Any]] | None = None
    min_decimal_places: float | None = None
    show_alert_threshold_lines: bool | None = None
    show_labels_on_series: bool | None = None
    show_legend: bool | None = None
    show_multiple_y_axes: bool | None = None
    show_percent_stack_view: bool | None = None
    show_values_on_series: bool | None = None
    smoothing_intervals: float | None = None
    y_axis_scale_type: YAxisScaleType | None = YAxisScaleType.LINEAR


@dataclass
class TrendsFormulaNode(SchemaModel):
    formula: str
    custom_name: str | None = None


@dataclass
class UserBasicType(SchemaModel):
    distinct_id: str
    email: str
    first_name: str
    id: float
    uuid: str
    hedgehog_config: MinimalHedgehogConfig | None = None
    is_email_verified: Any | None = None
    last_name: str | None = None


@dataclass
class VectorSearchResponseItem(SchemaModel):
    distance: float
    id: str


@dataclass
class ActionsPie(SchemaModel):
    disableHoverOffset: bool | None = None
    hideAggregation: bool | None = None


@dataclass
class RETENTION(SchemaModel):
    hideLineGraph: bool | None = None
    hideSizeColumn: bool | None = None
    useSmallLayout: bool | None = None


@dataclass
class VizSpecificOptions(SchemaModel):
    ActionsPie: ActionsPie | None = None
    RETENTION: RETENTION | None = None


@dataclass
class WebAnalyticsExternalSummaryRequest(SchemaModel):
    date_from: str
    date_to: str
    explicit_date: bool | None = None


class WebAnalyticsItemKind(StrEnum):
    UNIT = "unit"
    DURATION_S = "duration_s"
    PERCENTAGE = "percentage"
    CURRENCY = "currency"


class WebAnalyticsOrderByDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class WebAnalyticsOrderByFields(StrEnum):
    VISITORS = "Visitors"
    VIEWS = "Views"
    CLICKS = "Clicks"
    BOUNCE_RATE = "BounceRate"
    AVERAGE_SCROLL_PERCENTAGE = "AverageScrollPercentage"
    SCROLL_GT80_PERCENTAGE = "ScrollGt80Percentage"
    TOTAL_CONVERSIONS = "TotalConversions"
    UNIQUE_CONVERSIONS = "UniqueConversions"
    CONVERSION_RATE = "ConversionRate"
    CONVERTING_USERS = "ConvertingUsers"
    RAGE_CLICKS = "RageClicks"
    DEAD_CLICKS = "DeadClicks"
    ERRORS = "Errors"


@dataclass
class WebAnalyticsSampling(SchemaModel):
    enabled: bool | None = None
    forceSamplingRate: SamplingRate | None = None


@dataclass
class WebOverviewItem(SchemaModel):
    key: str
    kind: WebAnalyticsItemKind
    changeFromPreviousPct: float | None = None
    isIncreaseBad: bool | None = None
    previous: float | None = None
    usedPreAggregatedTables: bool | None = None
    value: float | None = None


class WebStatsBreakdown(StrEnum):
    PAGE = "Page"
    INITIAL_PAGE = "InitialPage"
    EXIT_PAGE = "ExitPage"
    EXIT_CLICK = "ExitClick"
    PREVIOUS_PAGE = "PreviousPage"
    SCREEN_NAME = "ScreenName"
    INITIAL_CHANNEL_TYPE = "InitialChannelType"
    INITIAL_REFERRING_DOMAIN = "InitialReferringDomain"
    INITIAL_UTM_SOURCE = "InitialUTMSource"
    INITIAL_UTM_CAMPAIGN = "InitialUTMCampaign"
    INITIAL_UTM_MEDIUM = "InitialUTMMedium"
    INITIAL_UTM_TERM = "InitialUTMTerm"
    INITIAL_UTM_CONTENT = "InitialUTMContent"
    INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN = "InitialUTMSourceMediumCampaign"
    BROWSER = "Browser"
    OS = "OS"
    VIEWPORT = "Viewport"
    DEVICE_TYPE = "DeviceType"
    COUNTRY = "Country"
    REGION = "Region"
    CITY = "City"
    TIMEZONE = "Timezone"
    LANGUAGE = "Language"
    FRUSTRATION_METRICS = "FrustrationMetrics"


@dataclass
class Metrics(SchemaModel):
    Bounces: float | None = None
    PageViews: float | None = None
    SessionDuration: float | None = None
    Sessions: float | None = None
    TotalSessions: float | None = None
    UniqueUsers: float | None = None


@dataclass
class WebTrendsItem(SchemaModel):
    bucket: str
    metrics: Metrics


class WebTrendsMetric(StrEnum):
    UNIQUE_USERS = "UniqueUsers"
    PAGE_VIEWS = "PageViews"
    SESSIONS = "Sessions"
    BOUNCES = "Bounces"
    SESSION_DURATION = "SessionDuration"
    TOTAL_SESSIONS = "TotalSessions"


class WebVitalsMetric(StrEnum):
    INP = "INP"
    LCP = "LCP"
    CLS = "CLS"
    FCP = "FCP"


class WebVitalsMetricBand(StrEnum):
    GOOD = "good"
    NEEDS_IMPROVEMENTS = "needs_improvements"
    POOR = "poor"


@dataclass
class WebVitalsPathBreakdownResultItem(SchemaModel):
    path: str
    value: float


class WebVitalsPercentile(StrEnum):
    P75 = "p75"
    P90 = "p90"
    P99 = "p99"


class Scale(StrEnum):
    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"


@dataclass
class YAxisSettings(SchemaModel):
    scale: Scale | None = None
    showGridLines: bool | None = None
    showTicks: bool | None = None
    startAtZero: bool | None = None


Integer = int


@dataclass
class ActionConversionGoal(SchemaModel):
    actionId: int


@dataclass
class ActorsPropertyTaxonomyResponse(SchemaModel):
    sample_count: int
    sample_values: list[Union[str, float, bool, int]]


@dataclass
class AlertCondition(SchemaModel):
    type: AlertConditionType


@dataclass
class AssistantArrayPropertyFilter(SchemaModel):
    operator: AssistantArrayPropertyFilterOperator
    value: list[str]


@dataclass
class AssistantBreakdownFilter(SchemaModel):
    breakdown_limit: int | None = 25


@dataclass
class AssistantDateTimePropertyFilter(SchemaModel):
    operator: AssistantDateTimePropertyFilterOperator
    value: str


@dataclass
class AssistantForm(SchemaModel):
    options: list[AssistantFormOption]


@dataclass
class AssistantFunnelsBreakdownFilter(SchemaModel):
    breakdown: str
    breakdown_group_type_index: int | None = None
    breakdown_limit: int | None = 25
    breakdown_type: AssistantFunnelsBreakdownType | None = AssistantFunnelsBreakdownType.EVENT


@dataclass
class AssistantFunnelsExclusionEventsNode(SchemaModel):
    event: str
    funnelFromStep: int
    funnelToStep: int
    kind: Literal["EventsNode"] = "EventsNode"


@dataclass
class AssistantFunnelsFilter(SchemaModel):
    binCount: int | None = None
    exclusions: list[AssistantFunnelsExclusionEventsNode] | None = field(default_factory=lambda: [])
    funnelAggregateByHogQL: FunnelAggregateByHogQL | None = None
    funnelOrderType: StepOrderValue | None = StepOrderValue.ORDERED
    funnelStepReference: FunnelStepReference | None = FunnelStepReference.TOTAL
    funnelVizType: FunnelVizType | None = FunnelVizType.STEPS
    funnelWindowInterval: int | None = 14
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | None = FunnelConversionWindowTimeUnit.DAY
    layout: FunnelLayout | None = FunnelLayout.VERTICAL


@dataclass
class AssistantGenerationStatusEvent(SchemaModel):
    type: AssistantGenerationStatusType


@dataclass
class AssistantGenericPropertyFilter1(SchemaModel):
    key: str
    operator: AssistantStringOrBooleanValuePropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: str


@dataclass
class AssistantGenericPropertyFilter2(SchemaModel):
    key: str
    operator: AssistantNumericValuePropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: float


@dataclass
class AssistantGenericPropertyFilter3(SchemaModel):
    key: str
    operator: AssistantArrayPropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: list[str]


@dataclass
class AssistantGenericPropertyFilter4(SchemaModel):
    key: str
    operator: AssistantDateTimePropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: str


@dataclass
class AssistantGenericPropertyFilter5(SchemaModel):
    key: str
    operator: AssistantSetPropertyFilterOperator
    type: AssistantGenericPropertyFilterType


@dataclass
class AssistantGroupMultipleBreakdownFilter(SchemaModel):
    property: str
    type: Literal["group"] = "group"
    group_type_index: int | None = None


@dataclass
class AssistantGroupPropertyFilter1(SchemaModel):
    group_type_index: int
    key: str
    operator: AssistantStringOrBooleanValuePropertyFilterOperator
    type: Literal["group"] = "group"
    value: str


@dataclass
class AssistantGroupPropertyFilter2(SchemaModel):
    group_type_index: int
    key: str
    operator: AssistantNumericValuePropertyFilterOperator
    type: Literal["group"] = "group"
    value: float


@dataclass
class AssistantGroupPropertyFilter3(SchemaModel):
    group_type_index: int
    key: str
    operator: AssistantArrayPropertyFilterOperator
    type: Literal["group"] = "group"
    value: list[str]


@dataclass
class AssistantGroupPropertyFilter4(SchemaModel):
    group_type_index: int
    key: str
    operator: AssistantDateTimePropertyFilterOperator
    type: Literal["group"] = "group"
    value: str


@dataclass
class AssistantGroupPropertyFilter5(SchemaModel):
    group_type_index: int
    key: str
    operator: AssistantSetPropertyFilterOperator
    type: Literal["group"] = "group"


@dataclass
class AssistantMessageMetadata(SchemaModel):
    form: AssistantForm | None = None


@dataclass
class AssistantNumericValuePropertyFilter(SchemaModel):
    operator: AssistantNumericValuePropertyFilterOperator
    value: float


@dataclass
class AssistantRetentionActionsNode(SchemaModel):
    id: float
    name: str
    type: Literal["actions"] = "actions"
    properties: (
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
        | None
    ) = None


@dataclass
class AssistantRetentionEventsNode(SchemaModel):
    name: str
    type: Literal["events"] = "events"
    custom_name: str | None = None
    properties: (
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
        | None
    ) = None


@dataclass
class AssistantSetPropertyFilter(SchemaModel):
    operator: AssistantSetPropertyFilterOperator


@dataclass
class AssistantStringOrBooleanValuePropertyFilter(SchemaModel):
    operator: AssistantStringOrBooleanValuePropertyFilterOperator
    value: str


@dataclass
class AssistantTrendsBreakdownFilter(SchemaModel):
    breakdowns: list[Union[AssistantGroupMultipleBreakdownFilter, AssistantGenericMultipleBreakdownFilter]]
    breakdown_limit: int | None = 25


@dataclass
class AutocompleteCompletionItem(SchemaModel):
    insertText: str
    kind: AutocompleteCompletionItemKind
    label: str
    detail: str | None = None
    documentation: str | None = None


@dataclass
class Breakdown(SchemaModel):
    property: Union[str, int]
    group_type_index: int | None = None
    histogram_bin_count: int | None = None
    normalize_url: bool | None = None
    type: MultipleBreakdownType | None = None


@dataclass
class BreakdownFilter(SchemaModel):
    breakdown: Union[str, list[Union[str, int]], int] | None = None
    breakdown_group_type_index: int | None = None
    breakdown_hide_other_aggregation: bool | None = None
    breakdown_histogram_bin_count: int | None = None
    breakdown_limit: int | None = None
    breakdown_normalize_url: bool | None = None
    breakdown_type: BreakdownType | None = BreakdownType.EVENT
    breakdowns: list[Breakdown] | None = None


@dataclass
class IntervalItem(SchemaModel):
    label: str
    value: int


@dataclass
class Series(SchemaModel):
    label: str
    value: int


@dataclass
class Settings(SchemaModel):
    display: ChartSettingsDisplay | None = None
    formatting: ChartSettingsFormatting | None = None


@dataclass
class ChartAxis(SchemaModel):
    column: str
    settings: Settings | None = None


@dataclass
class ChartSettings(SchemaModel):
    goalLines: list[GoalLine] | None = None
    leftYAxisSettings: YAxisSettings | None = None
    rightYAxisSettings: YAxisSettings | None = None
    seriesBreakdownColumn: str | None = None
    showLegend: bool | None = None
    showTotalRow: bool | None = None
    showXAxisBorder: bool | None = None
    showXAxisTicks: bool | None = None
    showYAxisBorder: bool | None = None
    stackBars100: bool | None = None
    xAxis: ChartAxis | None = None
    yAxis: list[ChartAxis] | None = None
    yAxisAtZero: bool | None = None


@dataclass
class ClickhouseQueryProgress(SchemaModel):
    active_cpu_time: int
    bytes_read: int
    estimated_rows_total: int
    rows_read: int
    time_elapsed: int


@dataclass
class CohortPropertyFilter(SchemaModel):
    key: Literal["id"] = "id"
    type: Literal["cohort"] = "cohort"
    value: int
    cohort_name: str | None = None
    label: str | None = None
    operator: PropertyOperator | None = PropertyOperator.IN_


@dataclass
class CustomChannelCondition(SchemaModel):
    id: str
    key: CustomChannelField
    op: CustomChannelOperator
    value: Union[str, list[str]] | None = None


@dataclass
class CustomChannelRule(SchemaModel):
    channel_type: str
    combiner: FilterLogicalOperator
    id: str
    items: list[CustomChannelCondition]


@dataclass
class DataTableNodeViewPropsContext(SchemaModel):
    type: DataTableNodeViewPropsContextType
    eventDefinitionId: str | None = None


@dataclass
class DataWarehousePersonPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["data_warehouse_person_property"] = "data_warehouse_person_property"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class DataWarehousePropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["data_warehouse"] = "data_warehouse"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class DataWarehouseViewLink(SchemaModel):
    id: str
    configuration: DataWarehouseViewLinkConfiguration | None = None
    created_at: str | None = None
    created_by: UserBasicType | None = None
    field_name: str | None = None
    joining_table_key: str | None = None
    joining_table_name: str | None = None
    source_table_key: str | None = None
    source_table_name: str | None = None


@dataclass
class DatabaseSchemaField(SchemaModel):
    hogql_value: str
    name: str
    schema_valid: bool
    type: DatabaseSerializedFieldType
    chain: list[Union[str, int]] | None = None
    fields: list[str] | None = None
    id: str | None = None
    table: str | None = None


@dataclass
class DatabaseSchemaPostHogTable(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    type: Literal["posthog"] = "posthog"
    row_count: float | None = None


@dataclass
class DatabaseSchemaSystemTable(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    type: Literal["system"] = "system"
    row_count: float | None = None


@dataclass
class DatabaseSchemaTableCommon(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    type: DatabaseSchemaTableType
    row_count: float | None = None


Day = int


@dataclass
class DeepResearchNotebook(SchemaModel):
    category: Literal["deep_research"] = "deep_research"
    notebook_id: str
    title: str
    notebook_type: DeepResearchType | None = None


@dataclass
class ElementPropertyFilter(SchemaModel):
    key: Key
    operator: PropertyOperator
    type: Literal["element"] = "element"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class ErrorTrackingExternalReferenceIntegration(SchemaModel):
    display_name: str
    id: float
    kind: IntegrationKind


@dataclass
class ErrorTrackingIssueAssignee(SchemaModel):
    id: Union[str, int]
    type: ErrorTrackingIssueAssigneeType


@dataclass
class ErrorTrackingIssueFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["error_tracking_issue"] = "error_tracking_issue"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class EventMetadataPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["event_metadata"] = "event_metadata"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class EventOddsRatioSerialized(SchemaModel):
    correlation_type: CorrelationType
    event: EventDefinition
    failure_count: int
    odds_ratio: float
    success_count: int


@dataclass
class EventPropertyFilter(SchemaModel):
    key: str
    type: Literal["event"] = "event"
    label: str | None = None
    operator: PropertyOperator | None = PropertyOperator.EXACT
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class EventTaxonomyItem(SchemaModel):
    property: str
    sample_count: int
    sample_values: list[str]


@dataclass
class EventsHeatMapColumnAggregationResult(SchemaModel):
    column: int
    value: int


@dataclass
class EventsHeatMapDataResult(SchemaModel):
    column: int
    row: int
    value: int


@dataclass
class EventsHeatMapRowAggregationResult(SchemaModel):
    row: int
    value: int


@dataclass
class EventsHeatMapStructuredResult(SchemaModel):
    allAggregations: int
    columnAggregations: list[EventsHeatMapColumnAggregationResult]
    data: list[EventsHeatMapDataResult]
    rowAggregations: list[EventsHeatMapRowAggregationResult]


@dataclass
class ExperimentExposureQueryResponse(SchemaModel):
    date_range: DateRange
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    timeseries: list[ExperimentExposureTimeSeries]
    total_exposures: dict[str, float]


@dataclass
class ExperimentHoldoutType(SchemaModel):
    created_at: str | None
    created_by: UserBasicType | None
    description: str | None
    filters: dict[str, Any]
    id: float | None
    name: str
    updated_at: str | None


@dataclass
class ExperimentMetricBaseProperties(SchemaModel):
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    fingerprint: str | None = None
    goal: ExperimentMetricGoal | None = None
    name: str | None = None
    response: dict[str, Any] | None = None
    uuid: str | None = None
    version: float | None = None


@dataclass
class ExperimentStatsBase(SchemaModel):
    key: str
    number_of_samples: int
    sum: float
    sum_squares: float
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    numerator_denominator_sum_product: float | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None


@dataclass
class ExperimentStatsBaseValidated(SchemaModel):
    key: str
    number_of_samples: int
    sum: float
    sum_squares: float
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    numerator_denominator_sum_product: float | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None
    validation_failures: list[ExperimentStatsValidationFailure] | None = None


@dataclass
class ExperimentVariantResultBayesian(SchemaModel):
    key: str
    method: Literal["bayesian"] = "bayesian"
    number_of_samples: int
    sum: float
    sum_squares: float
    chance_to_win: float | None = None
    credible_interval: list[float] | None = None
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    numerator_denominator_sum_product: float | None = None
    significant: bool | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None
    validation_failures: list[ExperimentStatsValidationFailure] | None = None


@dataclass
class ExperimentVariantResultFrequentist(SchemaModel):
    key: str
    method: Literal["frequentist"] = "frequentist"
    number_of_samples: int
    sum: float
    sum_squares: float
    confidence_interval: list[float] | None = None
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    numerator_denominator_sum_product: float | None = None
    p_value: float | None = None
    significant: bool | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None
    validation_failures: list[ExperimentStatsValidationFailure] | None = None


@dataclass
class ExternalQueryError(SchemaModel):
    code: ExternalQueryErrorCode
    detail: str


@dataclass
class FeaturePropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["feature"] = "feature"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class FunnelCorrelationResult(SchemaModel):
    events: list[EventOddsRatioSerialized]
    skewed: bool


@dataclass
class FunnelExclusionSteps(SchemaModel):
    funnelFromStep: int
    funnelToStep: int


@dataclass
class FunnelsFilterLegacy(SchemaModel):
    bin_count: Union[float, str] | None = None
    breakdown_attribution_type: BreakdownAttributionType | None = None
    breakdown_attribution_value: float | None = None
    exclusions: list[FunnelExclusionLegacy] | None = None
    funnel_aggregate_by_hogql: str | None = None
    funnel_from_step: float | None = None
    funnel_order_type: StepOrderValue | None = None
    funnel_step_reference: FunnelStepReference | None = None
    funnel_to_step: float | None = None
    funnel_viz_type: FunnelVizType | None = None
    funnel_window_interval: float | None = None
    funnel_window_interval_unit: FunnelConversionWindowTimeUnit | None = None
    hidden_legend_keys: dict[str, Union[bool, Any]] | None = None
    layout: FunnelLayout | None = None


@dataclass
class GroupPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["group"] = "group"
    group_type_index: int | None = None
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class HogQLAutocompleteResponse(SchemaModel):
    incomplete_list: bool
    suggestions: list[AutocompleteCompletionItem]
    timings: list[QueryTiming] | None = None


@dataclass
class HogQLNotice(SchemaModel):
    message: str
    end: int | None = None
    fix: str | None = None
    start: int | None = None


@dataclass
class HogQLPropertyFilter(SchemaModel):
    key: str
    type: Literal["hogql"] = "hogql"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class HogQLQueryModifiers(SchemaModel):
    bounceRateDurationSeconds: float | None = None
    bounceRatePageViewMode: BounceRatePageViewMode | None = None
    convertToProjectTimezone: bool | None = None
    customChannelTypeRules: list[CustomChannelRule] | None = None
    dataWarehouseEventsModifiers: list[DataWarehouseEventsModifier] | None = None
    debug: bool | None = None
    formatCsvAllowDoubleQuotes: bool | None = None
    inCohortVia: InCohortVia | None = None
    materializationMode: MaterializationMode | None = None
    optimizeJoinedFilters: bool | None = None
    personsArgMaxVersion: PersonsArgMaxVersion | None = None
    personsJoinMode: PersonsJoinMode | None = None
    personsOnEventsMode: PersonsOnEventsMode | None = None
    propertyGroupsMode: PropertyGroupsMode | None = None
    s3TableUseInvalidColumns: bool | None = None
    sessionTableVersion: SessionTableVersion | None = None
    sessionsV2JoinMode: SessionsV2JoinMode | None = None
    timings: bool | None = None
    useMaterializedViews: bool | None = None
    usePreaggregatedTableTransforms: bool | None = None
    usePresortedEventsTable: bool | None = None
    useWebAnalyticsPreAggregatedTables: bool | None = None


@dataclass
class HogQuery(SchemaModel):
    kind: Literal["HogQuery"] = "HogQuery"
    code: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: HogQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class DayItem(SchemaModel):
    label: str
    value: Union[str, int]


@dataclass
class InsightThreshold(SchemaModel):
    type: InsightThresholdType
    bounds: InsightsThresholdBounds | None = None


@dataclass
class LLMTrace(SchemaModel):
    createdAt: str
    events: list[LLMTraceEvent]
    id: str
    person: LLMTracePerson
    inputCost: float | None = None
    inputState: Any | None = None
    inputTokens: float | None = None
    outputCost: float | None = None
    outputState: Any | None = None
    outputTokens: float | None = None
    totalCost: float | None = None
    totalLatency: float | None = None
    traceName: str | None = None


@dataclass
class LifecycleFilter(SchemaModel):
    showLegend: bool | None = False
    showValuesOnSeries: bool | None = None
    stacked: bool | None = True
    toggledLifecycles: list[LifecycleToggle] | None = None


@dataclass
class LifecycleFilterLegacy(SchemaModel):
    show_legend: bool | None = None
    show_values_on_series: bool | None = None
    toggledLifecycles: list[LifecycleToggle] | None = None


@dataclass
class LogEntryPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["log_entry"] = "log_entry"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class LogMessage(SchemaModel):
    attributes: dict[str, Any]
    body: str
    event_name: str
    instrumentation_scope: str
    level: LogSeverityLevel
    observed_timestamp: str
    resource: str
    severity_number: float
    severity_text: LogSeverityLevel
    span_id: str
    timestamp: str
    trace_id: str
    uuid: str


@dataclass
class LogPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["log"] = "log"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class MarketingAnalyticsItem(SchemaModel):
    key: str
    kind: WebAnalyticsItemKind
    changeFromPreviousPct: float | None = None
    hasComparison: bool | None = None
    isIncreaseBad: bool | None = None
    previous: Union[float, str] | None = None
    value: Union[float, str] | None = None


@dataclass
class MarketingAnalyticsSchemaField(SchemaModel):
    isCurrency: bool
    required: bool
    type: list[MarketingAnalyticsSchemaFieldTypes]


@dataclass
class MatchedRecording(SchemaModel):
    events: list[MatchedRecordingEvent]
    session_id: str | None = None


@dataclass
class MaxBillingContextBillingPeriod(SchemaModel):
    current_period_end: str
    current_period_start: str
    interval: MaxBillingContextBillingPeriodInterval


@dataclass
class NewExperimentQueryResponse(SchemaModel):
    baseline: ExperimentStatsBaseValidated
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]


NotebookInfo = DeepResearchNotebook


@dataclass
class NotebookUpdateMessage(SchemaModel):
    content: ProsemirrorJSONContent
    notebook_id: str
    type: Literal["ai/notebook"] = "ai/notebook"
    conversation_notebooks: list[NotebookInfo] | None = None
    current_run_notebooks: list[NotebookInfo] | None = None
    id: str | None = None
    notebook_type: Literal["deep_research"] = "deep_research"
    tool_calls: list[AssistantToolCall] | None = None


@dataclass
class PathsFilter(SchemaModel):
    edgeLimit: int | None = 50
    endPoint: str | None = None
    excludeEvents: list[str] | None = None
    includeEventTypes: list[PathType] | None = None
    localPathCleaningFilters: list[PathCleaningFilter] | None = None
    maxEdgeWeight: int | None = None
    minEdgeWeight: int | None = None
    pathDropoffKey: str | None = None
    pathEndKey: str | None = None
    pathGroupings: list[str] | None = None
    pathReplacements: bool | None = None
    pathStartKey: str | None = None
    pathsHogQLExpression: str | None = None
    startPoint: str | None = None
    stepLimit: int | None = 5


@dataclass
class PersonPropertyFilter(SchemaModel):
    key: str
    operator: PropertyOperator
    type: Literal["person"] = "person"
    label: str | None = None
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


@dataclass
class PlanningStep(SchemaModel):
    description: str
    status: PlanningStepStatus


@dataclass
class QueryResponseAlternative8(SchemaModel):
    errors: list[HogQLNotice]
    notices: list[HogQLNotice]
    warnings: list[HogQLNotice]
    isUsingIndices: QueryIndexUsage | None = None
    isValid: bool | None = None
    query: str | None = None
    table_names: list[str] | None = None


@dataclass
class QueryResponseAlternative9(SchemaModel):
    incomplete_list: bool
    suggestions: list[AutocompleteCompletionItem]
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative25(SchemaModel):
    data: dict[str, Any]
    status: ExternalQueryStatus
    error: ExternalQueryError | None = None


@dataclass
class QueryStatus(SchemaModel):
    id: str
    team_id: int
    complete: bool | None = False
    dashboard_id: int | None = None
    end_time: str | None = None
    error: bool | None = False
    error_message: str | None = None
    expiration_time: str | None = None
    insight_id: int | None = None
    labels: list[str] | None = None
    pickup_time: str | None = None
    query_async: Literal[True] = True
    query_progress: ClickhouseQueryProgress | None = None
    results: Any | None = None
    start_time: str | None = None
    task_id: str | None = None


@dataclass
class QueryStatusResponse(SchemaModel):
    query_status: QueryStatus


ResultCustomization = Union[ResultCustomizationByValue, ResultCustomizationByPosition]


@dataclass
class RetentionValue(SchemaModel):
    count: int
    label: str | None = None


@dataclass
class RevenueAnalyticsAssistantFilters(SchemaModel):
    breakdown: list[RevenueAnalyticsBreakdown]
    properties: list[RevenueAnalyticsPropertyFilter]
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class RevenueAnalyticsEventItem(SchemaModel):
    eventName: str
    revenueProperty: str
    couponProperty: str | None = None
    currencyAwareDecimal: bool | None = False
    productProperty: str | None = None
    revenueCurrencyProperty: RevenueCurrencyPropertyConfig | None = field(default_factory=lambda: {"static": "USD"})
    subscriptionDropoffDays: float | None = 45
    subscriptionDropoffMode: SubscriptionDropoffMode | None = SubscriptionDropoffMode.LAST_EVENT
    subscriptionProperty: str | None = None


@dataclass
class RevenueAnalyticsGrossRevenueQueryResponse(SchemaModel):
    results: list
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class RevenueAnalyticsMRRQueryResponse(SchemaModel):
    results: list[RevenueAnalyticsMRRQueryResultItem]
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class RevenueAnalyticsMetricsQueryResponse(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class RevenueAnalyticsOverviewItem(SchemaModel):
    key: RevenueAnalyticsOverviewItemKey
    value: float


@dataclass
class RevenueAnalyticsOverviewQueryResponse(SchemaModel):
    results: list[RevenueAnalyticsOverviewItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class RevenueAnalyticsTopCustomersQueryResponse(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class RevenueExampleDataWarehouseTablesQueryResponse(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class RevenueExampleEventsQueryResponse(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class SavedInsightNode(SchemaModel):
    kind: Literal["SavedInsightNode"] = "SavedInsightNode"
    shortId: str
    allowSorting: bool | None = None
    context: DataTableNodeViewPropsContext | None = None
    embedded: bool | None = None
    expandable: bool | None = None
    full: bool | None = None
    hidePersonsModal: bool | None = None
    hideTooltipOnScroll: bool | None = None
    propertiesViaUrl: bool | None = None
    showActions: bool | None = None
    showColumnConfigurator: bool | None = None
    showCorrelationTable: bool | None = None
    showDateRange: bool | None = None
    showElapsedTime: bool | None = None
    showEventFilter: bool | None = None
    showExport: bool | None = None
    showFilters: bool | None = None
    showHeader: bool | None = None
    showHogQLEditor: bool | None = None
    showLastComputation: bool | None = None
    showLastComputationRefresh: bool | None = None
    showOpenEditorButton: bool | None = None
    showPersistentColumnConfigurator: bool | None = None
    showPropertyFilter: Union[bool, list[TaxonomicFilterGroupType]] | None = None
    showReload: bool | None = None
    showResults: bool | None = None
    showResultsTable: bool | None = None
    showSavedFilters: bool | None = None
    showSavedQueries: bool | None = None
    showSearch: bool | None = None
    showTable: bool | None = None
    showTestAccountFilters: bool | None = None
    showTimings: bool | None = None
    suppressSessionAnalysisWarning: bool | None = None
    version: float | None = None
    vizSpecificOptions: VizSpecificOptions | None = None


@dataclass
class Filters(SchemaModel):
    dateRange: DateRange | None = None
    properties: list[SessionPropertyFilter] | None = None


@dataclass
class SessionAttributionExplorerQueryResponse(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class SessionBatchEventsQueryResponse(SchemaModel):
    columns: list
    hogql: str
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    session_events: list[SessionEventsItem] | None = None
    sessions_with_no_events: list[str] | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class SessionRecordingType(SchemaModel):
    end_time: str
    id: str
    recording_duration: float
    snapshot_source: SnapshotSource
    start_time: str
    viewed: bool
    viewers: list[str]
    active_seconds: float | None = None
    activity_score: float | None = None
    click_count: float | None = None
    console_error_count: float | None = None
    console_log_count: float | None = None
    console_warn_count: float | None = None
    distinct_id: str | None = None
    email: str | None = None
    inactive_seconds: float | None = None
    keypress_count: float | None = None
    matching_events: list[MatchedRecording] | None = None
    mouse_activity_count: float | None = None
    ongoing: bool | None = None
    person: PersonType | None = None
    retention_period_days: float | None = None
    start_url: str | None = None
    storage: Storage | None = None
    summary: str | None = None


@dataclass
class SessionsTimelineQueryResponse(SchemaModel):
    results: list[TimelineEntry]
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class SourceFieldFileUploadConfig(SchemaModel):
    fileFormat: SourceFieldFileUploadJsonFormatConfig
    label: str
    name: str
    required: bool
    type: Literal["file-upload"] = "file-upload"


@dataclass
class SourceFieldInputConfig(SchemaModel):
    label: str
    name: str
    placeholder: str
    required: bool
    type: SourceFieldInputConfigType


@dataclass
class StickinessCriteria(SchemaModel):
    operator: StickinessOperator
    value: int


@dataclass
class StickinessFilter(SchemaModel):
    computedAs: StickinessComputationMode | None = None
    display: ChartDisplayType | None = None
    hiddenLegendIndexes: list[int] | None = None
    resultCustomizationBy: ResultCustomizationBy | None = ResultCustomizationBy.VALUE
    resultCustomizations: (
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]] | None
    ) = None
    showLegend: bool | None = None
    showMultipleYAxes: bool | None = None
    showValuesOnSeries: bool | None = None
    stickinessCriteria: StickinessCriteria | None = None


@dataclass
class StickinessQueryResponse(SchemaModel):
    results: list[dict[str, Any]]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class SuggestedQuestionsQuery(SchemaModel):
    kind: Literal["SuggestedQuestionsQuery"] = "SuggestedQuestionsQuery"
    modifiers: HogQLQueryModifiers | None = None
    response: SuggestedQuestionsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class SurveyAnalysisQuestionGroup(SchemaModel):
    questionId: str | None = "unknown"
    questionName: str | None = "Unknown question"
    responses: list[SurveyAnalysisResponseItem] | None = field(default_factory=lambda: [])


@dataclass
class SurveyAppearanceSchema(SchemaModel):
    backgroundColor: str | None = None
    borderColor: str | None = None
    buttonColor: str | None = None
    buttonTextColor: str | None = None
    inputBackground: str | None = None
    maxWidth: str | None = None
    placeholder: str | None = None
    position: SurveyPosition | None = None
    ratingButtonActiveColor: str | None = None
    ratingButtonColor: str | None = None
    shuffleQuestions: bool | None = None
    surveyPopupDelaySeconds: float | None = None
    textColor: str | None = None
    textSubtleColor: str | None = None
    thankYouMessageCloseButtonText: str | None = None
    thankYouMessageDescription: str | None = None
    thankYouMessageDescriptionContentType: SurveyQuestionDescriptionContentType | None = None
    thankYouMessageHeader: str | None = None
    whiteLabel: bool | None = None
    widgetColor: str | None = None
    widgetLabel: str | None = None
    widgetSelector: str | None = None
    widgetType: SurveyWidgetType | None = None
    zIndex: str | None = None


@dataclass
class SurveyDisplayConditionsSchema(SchemaModel):
    actions: Actions | None = None
    deviceTypes: list[str] | None = None
    deviceTypesMatchType: SurveyMatchType | None = None
    linkedFlagVariant: str | None = None
    seenSurveyWaitPeriodInDays: float | None = None
    selector: str | None = None
    url: str | None = None
    urlMatchType: SurveyMatchType | None = None


@dataclass
class SurveyQuestionSchema(SchemaModel):
    question: str
    type: SurveyQuestionType
    branching: Branching | None = None
    buttonText: str | None = None
    choices: list[str] | None = None
    description: str | None = None
    descriptionContentType: SurveyQuestionDescriptionContentType | None = None
    display: Display1 | None = None
    hasOpenChoice: bool | None = None
    id: str | None = None
    link: str | None = None
    lowerBoundLabel: str | None = None
    optional: bool | None = None
    scale: float | None = None
    shuffleOptions: bool | None = None
    upperBoundLabel: str | None = None


@dataclass
class TableSettings(SchemaModel):
    columns: list[ChartAxis] | None = None
    conditionalFormatting: list[ConditionalFormattingRule] | None = None


@dataclass
class TaskExecutionItem(SchemaModel):
    description: str
    id: str
    prompt: str
    status: TaskExecutionStatus
    task_type: str
    artifact_ids: list[str] | None = None
    progress_text: str | None = None


@dataclass
class TaskExecutionMessage(SchemaModel):
    tasks: list[TaskExecutionItem]
    type: Literal["ai/task_execution"] = "ai/task_execution"
    id: str | None = None


@dataclass
class TeamTaxonomyItem(SchemaModel):
    count: int
    event: str


@dataclass
class TestBasicQueryResponse(SchemaModel):
    results: list
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class TestCachedBasicQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class TraceQueryResponse(SchemaModel):
    results: list[LLMTrace]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class TracesQueryResponse(SchemaModel):
    results: list[LLMTrace]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class TrendsAlertConfig(SchemaModel):
    series_index: int
    type: Literal["TrendsAlertConfig"] = "TrendsAlertConfig"
    check_ongoing_interval: bool | None = None


@dataclass
class TrendsFilter(SchemaModel):
    aggregationAxisFormat: AggregationAxisFormat | None = AggregationAxisFormat.NUMERIC
    aggregationAxisPostfix: str | None = None
    aggregationAxisPrefix: str | None = None
    breakdown_histogram_bin_count: float | None = None
    confidenceLevel: float | None = None
    decimalPlaces: float | None = None
    detailedResultsAggregationType: DetailedResultsAggregationType | None = None
    display: ChartDisplayType | None = ChartDisplayType.ACTIONS_LINE_GRAPH
    formula: str | None = None
    formulaNodes: list[TrendsFormulaNode] | None = None
    formulas: list[str] | None = None
    goalLines: list[GoalLine] | None = None
    hiddenLegendIndexes: list[int] | None = None
    minDecimalPlaces: float | None = None
    movingAverageIntervals: float | None = None
    resultCustomizationBy: ResultCustomizationBy | None = ResultCustomizationBy.VALUE
    resultCustomizations: (
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]] | None
    ) = None
    showAlertThresholdLines: bool | None = False
    showConfidenceIntervals: bool | None = None
    showLabelsOnSeries: bool | None = None
    showLegend: bool | None = False
    showMovingAverage: bool | None = None
    showMultipleYAxes: bool | None = False
    showPercentStackView: bool | None = False
    showTrendLines: bool | None = None
    showValuesOnSeries: bool | None = False
    smoothingIntervals: int | None = 1
    yAxisScaleType: YAxisScaleType | None = YAxisScaleType.LINEAR


@dataclass
class TrendsQueryResponse(SchemaModel):
    results: list[dict[str, Any]]
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class WebAnalyticsExternalSummaryQueryResponse(SchemaModel):
    data: dict[str, Any]
    status: ExternalQueryStatus
    error: ExternalQueryError | None = None


@dataclass
class WebAnalyticsItemBaseNumberString(SchemaModel):
    key: str
    kind: WebAnalyticsItemKind
    changeFromPreviousPct: float | None = None
    isIncreaseBad: bool | None = None
    previous: Union[float, str] | None = None
    value: Union[float, str] | None = None


@dataclass
class WebAnalyticsItemBaseNumber(SchemaModel):
    key: str
    kind: WebAnalyticsItemKind
    changeFromPreviousPct: float | None = None
    isIncreaseBad: bool | None = None
    previous: float | None = None
    value: float | None = None


@dataclass
class WebExternalClicksTableQueryResponse(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class WebGoalsQueryResponse(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class WebOverviewQueryResponse(SchemaModel):
    results: list[WebOverviewItem]
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class WebPageURLSearchQueryResponse(SchemaModel):
    results: list[PageURL]
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class WebStatsTableQueryResponse(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class WebVitalsItemAction(SchemaModel):
    custom_name: WebVitalsMetric
    math: WebVitalsPercentile


@dataclass
class WebVitalsPathBreakdownResult(SchemaModel):
    good: list[WebVitalsPathBreakdownResultItem]
    needs_improvements: list[WebVitalsPathBreakdownResultItem]
    poor: list[WebVitalsPathBreakdownResultItem]


@dataclass
class ActorsPropertyTaxonomyQueryResponse(SchemaModel):
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class ActorsQueryResponse(SchemaModel):
    columns: list
    hogql: str
    limit: int
    offset: int
    results: list[list]
    error: str | None = None
    hasMore: bool | None = None
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list[str] | None = None


@dataclass
class AnalyticsQueryResponseBase(SchemaModel):
    results: Any
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class AssistantFunnelNodeShared(SchemaModel):
    math: AssistantFunnelsMath | None = None
    properties: (
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
        | None
    ) = None


@dataclass
class AssistantFunnelsActionsNode(SchemaModel):
    id: float
    kind: Literal["ActionsNode"] = "ActionsNode"
    name: str
    math: AssistantFunnelsMath | None = None
    properties: (
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
        | None
    ) = None
    version: float | None = None


@dataclass
class AssistantFunnelsEventsNode(SchemaModel):
    event: str
    kind: Literal["EventsNode"] = "EventsNode"
    custom_name: str | None = None
    math: AssistantFunnelsMath | None = None
    properties: (
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
        | None
    ) = None
    version: float | None = None


@dataclass
class AssistantFunnelsQuery(SchemaModel):
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
    series: list[Union[AssistantFunnelsEventsNode, AssistantFunnelsActionsNode]]
    aggregation_group_type_index: int | None = None
    breakdownFilter: AssistantFunnelsBreakdownFilter | None = None
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = None
    filterTestAccounts: bool | None = False
    funnelsFilter: AssistantFunnelsFilter | None = None
    interval: IntervalType | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    samplingFactor: float | None = None


@dataclass
class AssistantInsightsQueryBase(SchemaModel):
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = None
    filterTestAccounts: bool | None = False
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    samplingFactor: float | None = None


@dataclass
class AssistantMessage(SchemaModel):
    content: str
    type: Literal["ai"] = "ai"
    id: str | None = None
    meta: AssistantMessageMetadata | None = None
    tool_calls: list[AssistantToolCall] | None = None


@dataclass
class AssistantRetentionFilter(SchemaModel):
    returningEntity: Union[AssistantRetentionEventsNode, AssistantRetentionActionsNode]
    targetEntity: Union[AssistantRetentionEventsNode, AssistantRetentionActionsNode]
    cumulative: bool | None = None
    meanRetentionCalculation: MeanRetentionCalculation | None = None
    period: RetentionPeriod | None = RetentionPeriod.DAY
    retentionReference: RetentionReference | None = None
    retentionType: RetentionType | None = None
    totalIntervals: int | None = 11


@dataclass
class AssistantRetentionQuery(SchemaModel):
    kind: Literal["RetentionQuery"] = "RetentionQuery"
    retentionFilter: AssistantRetentionFilter
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = None
    filterTestAccounts: bool | None = False
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    samplingFactor: float | None = None


@dataclass
class AssistantTrendsActionsNode(SchemaModel):
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    name: str
    custom_name: str | None = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_type: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    version: float | None = None


@dataclass
class AssistantTrendsEventsNode(SchemaModel):
    kind: Literal["EventsNode"] = "EventsNode"
    custom_name: str | None = None
    event: str | None = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    version: float | None = None


@dataclass
class AssistantTrendsQuery(SchemaModel):
    kind: Literal["TrendsQuery"] = "TrendsQuery"
    series: list[Union[AssistantTrendsEventsNode, AssistantTrendsActionsNode]]
    breakdownFilter: AssistantTrendsBreakdownFilter | None = None
    compareFilter: CompareFilter | None = None
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = None
    filterTestAccounts: bool | None = False
    interval: IntervalType | None = IntervalType.DAY
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    samplingFactor: float | None = None
    trendsFilter: AssistantTrendsFilter | None = None


@dataclass
class BreakdownItem(SchemaModel):
    label: str
    value: Union[str, int]


@dataclass
class CacheMissResponse(SchemaModel):
    cache_key: str | None
    query_status: QueryStatus | None = None


@dataclass
class CachedActorsPropertyTaxonomyQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedActorsQueryResponse(SchemaModel):
    cache_key: str
    columns: list
    hogql: str
    is_cached: bool
    last_refresh: str
    limit: int
    next_allowed_client_refresh: str
    offset: int
    results: list[list]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list[str] | None = None


@dataclass
class CachedCalendarHeatmapQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: EventsHeatMapStructuredResult
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedEventTaxonomyQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[EventTaxonomyItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedEventsQueryResponse(SchemaModel):
    cache_key: str
    columns: list
    hogql: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[list]
    timezone: str
    types: list[str]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedExperimentExposureQueryResponse(SchemaModel):
    cache_key: str
    date_range: DateRange
    is_cached: bool
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    last_refresh: str
    next_allowed_client_refresh: str
    timeseries: list[ExperimentExposureTimeSeries]
    timezone: str
    total_exposures: dict[str, float]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None


@dataclass
class CachedFunnelCorrelationResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: FunnelCorrelationResult
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedFunnelsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Any
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    isUdf: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedGroupsQueryResponse(SchemaModel):
    cache_key: str
    columns: list
    hogql: str
    is_cached: bool
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    last_refresh: str
    limit: int
    next_allowed_client_refresh: str
    offset: int
    results: list[list]
    timezone: str
    types: list[str]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedLifecycleQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[dict[str, Any]]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedLogsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Any
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedMarketingAnalyticsTableQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[list[MarketingAnalyticsItem]]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedNewExperimentQueryResponse(SchemaModel):
    baseline: ExperimentStatsBaseValidated
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    timezone: str
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None


@dataclass
class CachedPathsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[PathsLink]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedRevenueAnalyticsGrossRevenueQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedRevenueAnalyticsMRRQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedRevenueAnalyticsMetricsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Any
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedRevenueAnalyticsOverviewQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[RevenueAnalyticsOverviewItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedRevenueAnalyticsTopCustomersQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Any
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedRevenueExampleDataWarehouseTablesQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Any
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedRevenueExampleEventsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Any
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedSessionAttributionExplorerQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: Any
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedSessionBatchEventsQueryResponse(SchemaModel):
    cache_key: str
    columns: list
    hogql: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[list]
    timezone: str
    types: list[str]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    session_events: list[SessionEventsItem] | None = None
    sessions_with_no_events: list[str] | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedSessionsTimelineQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[TimelineEntry]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedStickinessQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[dict[str, Any]]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedSuggestedQuestionsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    questions: list[str]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None


@dataclass
class CachedTeamTaxonomyQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[TeamTaxonomyItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedTraceQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[LLMTrace]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedTracesQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[LLMTrace]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedTrendsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[dict[str, Any]]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedVectorSearchQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[VectorSearchResponseItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedWebExternalClicksTableQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedWebGoalsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedWebOverviewQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[WebOverviewItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class CachedWebPageURLSearchQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[PageURL]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedWebStatsTableQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class CachedWebVitalsPathBreakdownQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[WebVitalsPathBreakdownResult]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CalendarHeatmapResponse(SchemaModel):
    results: EventsHeatMapStructuredResult
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class ConversionGoalFilter1(SchemaModel):
    conversion_goal_id: str
    conversion_goal_name: str
    kind: Literal["EventsNode"] = "EventsNode"
    schema_map: dict[str, Union[str, Any]]
    custom_name: str | None = None
    event: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    limit: int | None = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    orderBy: list[str] | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class ConversionGoalFilter2(SchemaModel):
    conversion_goal_id: str
    conversion_goal_name: str
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    schema_map: dict[str, Union[str, Any]]
    custom_name: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class ConversionGoalFilter3(SchemaModel):
    conversion_goal_id: str
    conversion_goal_name: str
    distinct_id_field: str
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
    schema_map: dict[str, Union[str, Any]]
    table_name: str
    timestamp_field: str
    custom_name: str | None = None
    dw_source_type: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class DashboardFilter(SchemaModel):
    breakdown_filter: BreakdownFilter | None = None
    date_from: str | None = None
    date_to: str | None = None
    properties: (
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
        | None
    ) = None


@dataclass
class Response(SchemaModel):
    columns: list
    hogql: str
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response1(SchemaModel):
    columns: list
    hogql: str
    limit: int
    offset: int
    results: list[list]
    error: str | None = None
    hasMore: bool | None = None
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list[str] | None = None


@dataclass
class Response2(SchemaModel):
    columns: list
    hogql: str
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    offset: int
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response4(SchemaModel):
    results: list[WebOverviewItem]
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class Response5(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class Response6(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class Response8(SchemaModel):
    results: list[WebVitalsPathBreakdownResult]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response9(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class Response10(SchemaModel):
    results: list
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response11(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response12(SchemaModel):
    results: list[RevenueAnalyticsMRRQueryResultItem]
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response13(SchemaModel):
    results: list[RevenueAnalyticsOverviewItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response14(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response15(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class Response17(SchemaModel):
    results: list[list[MarketingAnalyticsItem]]
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class Response22(SchemaModel):
    results: list[LLMTrace]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class DataWarehouseNode(SchemaModel):
    distinct_id_field: str
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
    table_name: str
    timestamp_field: str
    custom_name: str | None = None
    dw_source_type: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class DatabaseSchemaBatchExportTable(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    type: Literal["batch_export"] = "batch_export"
    row_count: float | None = None


@dataclass
class DatabaseSchemaDataWarehouseTable(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    format: str
    id: str
    name: str
    type: Literal["data_warehouse"] = "data_warehouse"
    url_pattern: str
    row_count: float | None = None
    schema_: DatabaseSchemaSchema | None = None
    source: DatabaseSchemaSource | None = None


@dataclass
class EntityNode(SchemaModel):
    kind: NodeKind
    custom_name: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class ErrorTrackingExternalReference(SchemaModel):
    external_url: str
    id: str
    integration: ErrorTrackingExternalReferenceIntegration


@dataclass
class ErrorTrackingIssue(SchemaModel):
    assignee: ErrorTrackingIssueAssignee | None
    description: str | None
    first_seen: str
    id: str
    last_seen: str
    library: str | None
    name: str | None
    status: Status
    aggregations: ErrorTrackingIssueAggregations | None = None
    external_issues: list[ErrorTrackingExternalReference] | None = None
    first_event: FirstEvent | None = None
    last_event: LastEvent | None = None


@dataclass
class ErrorTrackingIssueFilteringToolOutput(SchemaModel):
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = None
    newFilters: (
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
        | None
    ) = None
    orderBy: OrderBy | None = None
    orderDirection: OrderDirection | None = None
    removedFilterIndexes: list[int] | None = None
    searchQuery: str | None = None
    status: Status2 | None = None


@dataclass
class ErrorTrackingQueryResponse(SchemaModel):
    results: list[ErrorTrackingIssue]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class ErrorTrackingRelationalIssue(SchemaModel):
    assignee: ErrorTrackingIssueAssignee | None
    description: str | None
    first_seen: str
    id: str
    name: str | None
    status: Status4
    external_issues: list[ErrorTrackingExternalReference] | None = None


@dataclass
class EventTaxonomyQueryResponse(SchemaModel):
    results: list[EventTaxonomyItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class EventsNode(SchemaModel):
    kind: Literal["EventsNode"] = "EventsNode"
    custom_name: str | None = None
    event: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    limit: int | None = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    orderBy: list[str] | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class EventsQueryResponse(SchemaModel):
    columns: list
    hogql: str
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class ExperimentDataWarehouseNode(SchemaModel):
    data_warehouse_join_key: str
    events_join_key: str
    kind: Literal["ExperimentDataWarehouseNode"] = "ExperimentDataWarehouseNode"
    table_name: str
    timestamp_field: str
    custom_name: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class ExperimentEventExposureConfig(SchemaModel):
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
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class ExperimentExposureCriteria(SchemaModel):
    exposure_config: ExperimentEventExposureConfig | None = None
    filterTestAccounts: bool | None = None
    multiple_variant_handling: MultipleVariantHandling | None = None


@dataclass
class ExperimentExposureQuery(SchemaModel):
    end_date: str | None
    experiment_name: str
    feature_flag: dict[str, Any]
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    start_date: str | None
    experiment_id: int | None = None
    exposure_criteria: ExperimentExposureCriteria | None = None
    holdout: ExperimentHoldoutType | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: ExperimentExposureQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class FunnelCorrelationResponse(SchemaModel):
    results: FunnelCorrelationResult
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class FunnelExclusionActionsNode(SchemaModel):
    funnelFromStep: int
    funnelToStep: int
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    custom_name: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class FunnelExclusionEventsNode(SchemaModel):
    funnelFromStep: int
    funnelToStep: int
    kind: Literal["EventsNode"] = "EventsNode"
    custom_name: str | None = None
    event: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    limit: int | None = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    orderBy: list[str] | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class FunnelsQueryResponse(SchemaModel):
    results: Any
    error: str | None = None
    hogql: str | None = None
    isUdf: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class GenericCachedQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None


@dataclass
class GroupsQueryResponse(SchemaModel):
    columns: list
    hogql: str
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    offset: int
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


HeatMapQuerySource = EventsNode


@dataclass
class HogQLFilters(SchemaModel):
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = None
    properties: (
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
        | None
    ) = None


@dataclass
class HogQLMetadataResponse(SchemaModel):
    errors: list[HogQLNotice]
    notices: list[HogQLNotice]
    warnings: list[HogQLNotice]
    isUsingIndices: QueryIndexUsage | None = None
    isValid: bool | None = None
    query: str | None = None
    table_names: list[str] | None = None


@dataclass
class HogQLQueryResponse(SchemaModel):
    results: list
    clickhouse: str | None = None
    columns: list | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query: str | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class InsightActorsQueryBase(SchemaModel):
    kind: NodeKind
    includeRecordings: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: ActorsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class LifecycleQueryResponse(SchemaModel):
    results: list[dict[str, Any]]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class LogsQueryResponse(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class MarketingAnalyticsConfig(SchemaModel):
    conversion_goals: list[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]] | None = None
    sources_map: dict[str, SourceMap] | None = None


@dataclass
class MarketingAnalyticsTableQueryResponse(SchemaModel):
    results: list[list[MarketingAnalyticsItem]]
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class MaxBillingContext(SchemaModel):
    billing_plan: str | None
    has_active_subscription: bool
    products: list[MaxProductInfo]
    settings: MaxBillingContextSettings
    subscription_level: MaxBillingContextSubscriptionLevel
    billing_period: MaxBillingContextBillingPeriod | None = None
    is_deactivated: bool | None = None
    projected_total_amount_usd: str | None = None
    projected_total_amount_usd_after_discount: str | None = None
    projected_total_amount_usd_with_limit: str | None = None
    projected_total_amount_usd_with_limit_after_discount: str | None = None
    spend_history: list[SpendHistoryItem] | None = None
    startup_program_label: str | None = None
    startup_program_label_previous: str | None = None
    total_current_amount_usd: str | None = None
    trial: MaxBillingContextTrial | None = None
    usage_history: list[UsageHistoryItem] | None = None


@dataclass
class MultipleBreakdownOptions(SchemaModel):
    values: list[BreakdownItem]


@dataclass
class NamedQueryRunRequest(SchemaModel):
    client_query_id: str | None = None
    filters_override: DashboardFilter | None = None
    query_override: dict[str, Any] | None = None
    refresh: RefreshType | None = RefreshType.BLOCKING
    variables_override: dict[str, dict[str, Any]] | None = None
    variables_values: dict[str, Any] | None = None


@dataclass
class PathsQueryResponse(SchemaModel):
    results: list[PathsLink]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class PersonsNode(SchemaModel):
    kind: Literal["PersonsNode"] = "PersonsNode"
    cohort: int | None = None
    distinctId: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    search: str | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class PlanningMessage(SchemaModel):
    steps: list[PlanningStep]
    type: Literal["ai/planning"] = "ai/planning"
    id: str | None = None


@dataclass
class PropertyGroupFilterValue(SchemaModel):
    type: FilterLogicalOperator
    values: list[
        Union[
            PropertyGroupFilterValue,
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
            ],
        ]
    ]


@dataclass
class QueryResponseAlternative1(SchemaModel):
    columns: list
    hogql: str
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative2(SchemaModel):
    columns: list
    hogql: str
    limit: int
    offset: int
    results: list[list]
    error: str | None = None
    hasMore: bool | None = None
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list[str] | None = None


@dataclass
class QueryResponseAlternative3(SchemaModel):
    columns: list
    hogql: str
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    offset: int
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative4(SchemaModel):
    breakdown: list[BreakdownItem] | None = None
    breakdowns: list[MultipleBreakdownOptions] | None = None
    compare: list[CompareItem] | None = None
    day: list[DayItem] | None = None
    interval: list[IntervalItem] | None = None
    series: list[Series] | None = None
    status: list[StatusItem] | None = None


@dataclass
class QueryResponseAlternative5(SchemaModel):
    results: list[TimelineEntry]
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative7(SchemaModel):
    results: list
    clickhouse: str | None = None
    columns: list | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query: str | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative10(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative13(SchemaModel):
    results: list[ErrorTrackingIssue]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative19(SchemaModel):
    results: list[WebOverviewItem]
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class QueryResponseAlternative20(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class QueryResponseAlternative21(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative23(SchemaModel):
    results: list[WebVitalsPathBreakdownResult]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative24(SchemaModel):
    results: list[PageURL]
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative26(SchemaModel):
    results: list
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative27(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative28(SchemaModel):
    results: list[RevenueAnalyticsMRRQueryResultItem]
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative29(SchemaModel):
    results: list[RevenueAnalyticsOverviewItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative30(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative31(SchemaModel):
    results: list[list[MarketingAnalyticsItem]]
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative32(SchemaModel):
    columns: list
    hogql: str
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative33(SchemaModel):
    columns: list
    hogql: str
    limit: int
    offset: int
    results: list[list]
    error: str | None = None
    hasMore: bool | None = None
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list[str] | None = None


@dataclass
class QueryResponseAlternative34(SchemaModel):
    columns: list
    hogql: str
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    offset: int
    results: list[list]
    types: list[str]
    error: str | None = None
    hasMore: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative35(SchemaModel):
    results: list
    clickhouse: str | None = None
    columns: list | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query: str | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative36(SchemaModel):
    results: list[WebOverviewItem]
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class QueryResponseAlternative37(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class QueryResponseAlternative38(SchemaModel):
    results: list
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative40(SchemaModel):
    results: list[WebVitalsPathBreakdownResult]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative41(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative42(SchemaModel):
    results: list
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative43(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative44(SchemaModel):
    results: list[RevenueAnalyticsMRRQueryResultItem]
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative45(SchemaModel):
    results: list[RevenueAnalyticsOverviewItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative46(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative47(SchemaModel):
    results: Any
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative49(SchemaModel):
    results: list[list[MarketingAnalyticsItem]]
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative50(SchemaModel):
    results: list[ErrorTrackingIssue]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative54(SchemaModel):
    results: list[LLMTrace]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative55(SchemaModel):
    results: list[dict[str, Any]]
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative56(SchemaModel):
    results: Any
    error: str | None = None
    hogql: str | None = None
    isUdf: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative58(SchemaModel):
    results: list[PathsLink]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative59(SchemaModel):
    results: list[dict[str, Any]]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative61(SchemaModel):
    results: FunnelCorrelationResult
    columns: list | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class QueryResponseAlternative63(SchemaModel):
    results: Any
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative65(SchemaModel):
    results: list[TeamTaxonomyItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative66(SchemaModel):
    results: list[EventTaxonomyItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative67(SchemaModel):
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative68(SchemaModel):
    results: list[LLMTrace]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative70(SchemaModel):
    results: list[VectorSearchResponseItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class RecordingsQueryResponse(SchemaModel):
    has_next: bool
    results: list[SessionRecordingType]


@dataclass
class RetentionEntity(SchemaModel):
    custom_name: str | None = None
    id: Union[str, float] | None = None
    kind: RetentionEntityKind | None = None
    name: str | None = None
    order: int | None = None
    properties: (
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
        | None
    ) = None
    type: EntityType | None = None
    uuid: str | None = None


@dataclass
class RetentionFilter(SchemaModel):
    cumulative: bool | None = None
    dashboardDisplay: RetentionDashboardDisplayType | None = None
    display: ChartDisplayType | None = None
    meanRetentionCalculation: MeanRetentionCalculation | None = None
    minimumOccurrences: int | None = None
    period: RetentionPeriod | None = RetentionPeriod.DAY
    retentionReference: RetentionReference | None = None
    retentionType: RetentionType | None = None
    returningEntity: RetentionEntity | None = None
    showTrendLines: bool | None = None
    targetEntity: RetentionEntity | None = None
    totalIntervals: int | None = 8


@dataclass
class RetentionFilterLegacy(SchemaModel):
    cumulative: bool | None = None
    mean_retention_calculation: MeanRetentionCalculation | None = None
    period: RetentionPeriod | None = None
    retention_reference: RetentionReference | None = None
    retention_type: RetentionType | None = None
    returning_entity: RetentionEntity | None = None
    show_mean: bool | None = None
    target_entity: RetentionEntity | None = None
    total_intervals: int | None = None


@dataclass
class RetentionResult(SchemaModel):
    date: str
    label: str
    values: list[RetentionValue]
    breakdown_value: Union[str, float] | None = None


@dataclass
class RevenueAnalyticsBaseQueryRevenueAnalyticsGrossRevenueQueryResponse(SchemaModel):
    kind: NodeKind
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsGrossRevenueQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsBaseQueryRevenueAnalyticsMRRQueryResponse(SchemaModel):
    kind: NodeKind
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsMRRQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsBaseQueryRevenueAnalyticsMetricsQueryResponse(SchemaModel):
    kind: NodeKind
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsMetricsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsBaseQueryRevenueAnalyticsOverviewQueryResponse(SchemaModel):
    kind: NodeKind
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsOverviewQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsBaseQueryRevenueAnalyticsTopCustomersQueryResponse(SchemaModel):
    kind: NodeKind
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsTopCustomersQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsConfig(SchemaModel):
    events: list[RevenueAnalyticsEventItem] | None = field(default_factory=lambda: [])
    filter_test_accounts: bool | None = False
    goals: list[RevenueAnalyticsGoal] | None = field(default_factory=lambda: [])


@dataclass
class RevenueAnalyticsGrossRevenueQuery(SchemaModel):
    breakdown: list[RevenueAnalyticsBreakdown]
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsGrossRevenueQuery"] = "RevenueAnalyticsGrossRevenueQuery"
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsGrossRevenueQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsMRRQuery(SchemaModel):
    breakdown: list[RevenueAnalyticsBreakdown]
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMRRQuery"] = "RevenueAnalyticsMRRQuery"
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsMRRQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsMetricsQuery(SchemaModel):
    breakdown: list[RevenueAnalyticsBreakdown]
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMetricsQuery"] = "RevenueAnalyticsMetricsQuery"
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsMetricsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsOverviewQuery(SchemaModel):
    kind: Literal["RevenueAnalyticsOverviewQuery"] = "RevenueAnalyticsOverviewQuery"
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsOverviewQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueAnalyticsTopCustomersQuery(SchemaModel):
    groupBy: RevenueAnalyticsTopCustomersGroupBy
    kind: Literal["RevenueAnalyticsTopCustomersQuery"] = "RevenueAnalyticsTopCustomersQuery"
    properties: list[RevenueAnalyticsPropertyFilter]
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: RevenueAnalyticsTopCustomersQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueExampleDataWarehouseTablesQuery(SchemaModel):
    kind: Literal["RevenueExampleDataWarehouseTablesQuery"] = "RevenueExampleDataWarehouseTablesQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    response: RevenueExampleDataWarehouseTablesQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class RevenueExampleEventsQuery(SchemaModel):
    kind: Literal["RevenueExampleEventsQuery"] = "RevenueExampleEventsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    response: RevenueExampleEventsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class SessionAttributionExplorerQuery(SchemaModel):
    groupBy: list[SessionAttributionGroupBy]
    kind: Literal["SessionAttributionExplorerQuery"] = "SessionAttributionExplorerQuery"
    filters: Filters | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    response: SessionAttributionExplorerQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class SessionsTimelineQuery(SchemaModel):
    kind: Literal["SessionsTimelineQuery"] = "SessionsTimelineQuery"
    after: str | None = None
    before: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    personId: str | None = None
    response: SessionsTimelineQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class SurveyCreationSchema(SchemaModel):
    description: str
    name: str
    questions: list[SurveyQuestionSchema]
    type: SurveyType
    appearance: SurveyAppearanceSchema | None = None
    archived: bool | None = None
    conditions: SurveyDisplayConditionsSchema | None = None
    enable_partial_responses: bool | None = None
    end_date: str | None = None
    iteration_count: float | None = None
    iteration_frequency_days: float | None = None
    linked_flag_id: float | None = None
    responses_limit: float | None = None
    should_launch: bool | None = None
    start_date: str | None = None


@dataclass
class TeamTaxonomyQueryResponse(SchemaModel):
    results: list[TeamTaxonomyItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class TileFilters(SchemaModel):
    breakdown_filter: BreakdownFilter | None = None
    date_from: str | None = None
    date_to: str | None = None
    properties: (
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
        | None
    ) = None


@dataclass
class TraceQuery(SchemaModel):
    kind: Literal["TraceQuery"] = "TraceQuery"
    traceId: str
    dateRange: DateRange | None = None
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = None
    response: TraceQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class TracesQuery(SchemaModel):
    kind: Literal["TracesQuery"] = "TracesQuery"
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    properties: (
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
        | None
    ) = None
    response: TracesQueryResponse | None = None
    showColumnConfigurator: bool | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class VectorSearchQueryResponse(SchemaModel):
    results: list[VectorSearchResponseItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class WebAnalyticsExternalSummaryQuery(SchemaModel):
    dateRange: DateRange
    kind: Literal["WebAnalyticsExternalSummaryQuery"] = "WebAnalyticsExternalSummaryQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebAnalyticsExternalSummaryQueryResponse | None = None
    version: float | None = None


@dataclass
class WebExternalClicksTableQuery(SchemaModel):
    kind: Literal["WebExternalClicksTableQuery"] = "WebExternalClicksTableQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebExternalClicksTableQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    stripQueryParams: bool | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class WebGoalsQuery(SchemaModel):
    kind: Literal["WebGoalsQuery"] = "WebGoalsQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebGoalsQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class WebOverviewQuery(SchemaModel):
    kind: Literal["WebOverviewQuery"] = "WebOverviewQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebOverviewQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class WebPageURLSearchQuery(SchemaModel):
    kind: Literal["WebPageURLSearchQuery"] = "WebPageURLSearchQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebPageURLSearchQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    searchTerm: str | None = None
    stripQueryParams: bool | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class WebStatsTableQuery(SchemaModel):
    breakdownBy: WebStatsBreakdown
    kind: Literal["WebStatsTableQuery"] = "WebStatsTableQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeBounceRate: bool | None = None
    includeRevenue: bool | None = None
    includeScrollDepth: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebStatsTableQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class WebTrendsQueryResponse(SchemaModel):
    results: list[WebTrendsItem]
    clickhouse: str | None = None
    columns: list | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query: str | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class WebVitalsItem(SchemaModel):
    action: WebVitalsItemAction
    data: list[float]
    days: list[str]


@dataclass
class WebVitalsPathBreakdownQueryResponse(SchemaModel):
    results: list[WebVitalsPathBreakdownResult]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class WebVitalsQueryResponse(SchemaModel):
    results: list[WebVitalsItem]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class ActionsNode(SchemaModel):
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    custom_name: str | None = None
    fixedProperties: (
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
        | None
    ) = None
    math: (
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
        | None
    ) = None
    math_group_type_index: MathGroupTypeIndex | None = None
    math_hogql: str | None = None
    math_multiplier: float | None = None
    math_property: str | None = None
    math_property_revenue_currency: RevenueCurrencyPropertyConfig | None = None
    math_property_type: str | None = None
    name: str | None = None
    optionalInFunnel: bool | None = None
    properties: (
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
        | None
    ) = None
    response: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class ActorsPropertyTaxonomyQuery(SchemaModel):
    kind: Literal["ActorsPropertyTaxonomyQuery"] = "ActorsPropertyTaxonomyQuery"
    properties: list[str]
    groupTypeIndex: int | None = None
    maxPropertyValues: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: ActorsPropertyTaxonomyQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


AnyResponseType = Union[
    dict[str, Any],
    HogQueryResponse,
    HogQLQueryResponse,
    HogQLMetadataResponse,
    HogQLAutocompleteResponse,
    Any,
    EventsQueryResponse,
    ErrorTrackingQueryResponse,
    LogsQueryResponse,
]


AssistantBasePropertyFilter = Union[
    AssistantDateTimePropertyFilter,
    AssistantSetPropertyFilter,
    Union[
        AssistantStringOrBooleanValuePropertyFilter, AssistantNumericValuePropertyFilter, AssistantArrayPropertyFilter
    ],
]


@dataclass
class CachedErrorTrackingQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[ErrorTrackingIssue]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedHogQLQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    clickhouse: str | None = None
    columns: list | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query: str | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class CachedInsightActorsQueryOptionsResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    timezone: str
    breakdown: list[BreakdownItem] | None = None
    breakdowns: list[MultipleBreakdownOptions] | None = None
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    compare: list[CompareItem] | None = None
    day: list[DayItem] | None = None
    interval: list[IntervalItem] | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    series: list[Series] | None = None
    status: list[StatusItem] | None = None


@dataclass
class CachedRetentionQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[RetentionResult]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedWebTrendsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[WebTrendsItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    clickhouse: str | None = None
    columns: list | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query: str | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


@dataclass
class CachedWebVitalsQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[WebVitalsItem]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response3(SchemaModel):
    results: list
    clickhouse: str | None = None
    columns: list | None = None
    error: str | None = None
    explain: list[str] | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query: str | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None
    types: list | None = None


@dataclass
class Response18(SchemaModel):
    results: list[ErrorTrackingIssue]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class ErrorTrackingCorrelatedIssue(SchemaModel):
    assignee: ErrorTrackingIssueAssignee | None
    description: str | None
    event: str
    first_seen: str
    id: str
    last_seen: str
    library: str | None
    name: str | None
    odds_ratio: float
    population: Population
    status: Status
    external_issues: list[ErrorTrackingExternalReference] | None = None


@dataclass
class ErrorTrackingIssueCorrelationQueryResponse(SchemaModel):
    results: list[ErrorTrackingCorrelatedIssue]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class EventTaxonomyQuery(SchemaModel):
    kind: Literal["EventTaxonomyQuery"] = "EventTaxonomyQuery"
    actionId: int | None = None
    event: str | None = None
    maxPropertyValues: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    properties: list[str] | None = None
    response: EventTaxonomyQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class ExperimentFunnelMetricTypeProps(SchemaModel):
    metric_type: Literal["funnel"] = "funnel"
    series: list[Union[EventsNode, ActionsNode]]
    funnel_order_type: StepOrderValue | None = None


@dataclass
class ExperimentRatioMetric(SchemaModel):
    denominator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    metric_type: Literal["ratio"] = "ratio"
    numerator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    fingerprint: str | None = None
    goal: ExperimentMetricGoal | None = None
    name: str | None = None
    response: dict[str, Any] | None = None
    uuid: str | None = None
    version: float | None = None


@dataclass
class ExperimentRatioMetricTypeProps(SchemaModel):
    denominator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    metric_type: Literal["ratio"] = "ratio"
    numerator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]


@dataclass
class FunnelsFilter(SchemaModel):
    binCount: int | None = None
    breakdownAttributionType: BreakdownAttributionType | None = BreakdownAttributionType.FIRST_TOUCH
    breakdownAttributionValue: int | None = None
    exclusions: list[Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]] | None = field(
        default_factory=lambda: []
    )
    funnelAggregateByHogQL: str | None = None
    funnelFromStep: int | None = None
    funnelOrderType: StepOrderValue | None = StepOrderValue.ORDERED
    funnelStepReference: FunnelStepReference | None = FunnelStepReference.TOTAL
    funnelToStep: int | None = None
    funnelVizType: FunnelVizType | None = FunnelVizType.STEPS
    funnelWindowInterval: int | None = 14
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | None = FunnelConversionWindowTimeUnit.DAY
    goalLines: list[GoalLine] | None = None
    hiddenLegendBreakdowns: list[str] | None = None
    layout: FunnelLayout | None = FunnelLayout.VERTICAL
    resultCustomizations: dict[str, ResultCustomizationByValue] | None = None
    showValuesOnSeries: bool | None = False
    useUdf: bool | None = None


@dataclass
class GroupsQuery(SchemaModel):
    group_type_index: int
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: list[str] | None = None
    properties: list[Union[GroupPropertyFilter, HogQLPropertyFilter]] | None = None
    response: GroupsQueryResponse | None = None
    search: str | None = None
    select: list[str] | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class HogQLASTQuery(SchemaModel):
    kind: Literal["HogQLASTQuery"] = "HogQLASTQuery"
    query: dict[str, Any]
    explain: bool | None = None
    filters: HogQLFilters | None = None
    modifiers: HogQLQueryModifiers | None = None
    name: str | None = None
    response: HogQLQueryResponse | None = None
    tags: QueryLogTags | None = None
    values: dict[str, Any] | None = None
    variables: dict[str, HogQLVariable] | None = None
    version: float | None = None


@dataclass
class HogQLQuery(SchemaModel):
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    query: str
    explain: bool | None = None
    filters: HogQLFilters | None = None
    modifiers: HogQLQueryModifiers | None = None
    name: str | None = None
    response: HogQLQueryResponse | None = None
    tags: QueryLogTags | None = None
    values: dict[str, Any] | None = None
    variables: dict[str, HogQLVariable] | None = None
    version: float | None = None


@dataclass
class InsightActorsQueryOptionsResponse(SchemaModel):
    breakdown: list[BreakdownItem] | None = None
    breakdowns: list[MultipleBreakdownOptions] | None = None
    compare: list[CompareItem] | None = None
    day: list[DayItem] | None = None
    interval: list[IntervalItem] | None = None
    series: list[Series] | None = None
    status: list[StatusItem] | None = None


InsightFilter = Union[
    TrendsFilter, FunnelsFilter, RetentionFilter, PathsFilter, StickinessFilter, LifecycleFilter, CalendarHeatmapFilter
]


@dataclass
class MarketingAnalyticsTableQuery(SchemaModel):
    kind: Literal["MarketingAnalyticsTableQuery"] = "MarketingAnalyticsTableQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    draftConversionGoal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3] | None = None
    filterTestAccounts: bool | None = None
    includeAllConversions: bool | None = None
    includeRevenue: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: list[list[Union[str, MarketingAnalyticsOrderByEnum]]] | None = None
    response: MarketingAnalyticsTableQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    select: list[str] | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class MaxInnerUniversalFiltersGroup(SchemaModel):
    type: FilterLogicalOperator
    values: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter, RecordingPropertyFilter]]


@dataclass
class MaxOuterUniversalFiltersGroup(SchemaModel):
    type: FilterLogicalOperator
    values: list[MaxInnerUniversalFiltersGroup]


@dataclass
class MaxRecordingUniversalFilters(SchemaModel):
    duration: list[RecordingDurationFilter]
    filter_group: MaxOuterUniversalFiltersGroup
    date_from: str | None = None
    date_to: str | None = None
    filter_test_accounts: bool | None = None
    order: RecordingOrder | None = RecordingOrder.START_TIME
    order_direction: RecordingOrderDirection | None = RecordingOrderDirection.DESC


@dataclass
class PropertyGroupFilter(SchemaModel):
    type: FilterLogicalOperator
    values: list[PropertyGroupFilterValue]


@dataclass
class QueryResponseAlternative14(SchemaModel):
    results: list[ErrorTrackingCorrelatedIssue]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class QueryResponseAlternative57(SchemaModel):
    results: list[RetentionResult]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class RecordingsQuery(SchemaModel):
    kind: Literal["RecordingsQuery"] = "RecordingsQuery"
    actions: list[dict[str, Any]] | None = None
    comment_text: RecordingPropertyFilter | None = None
    console_log_filters: list[LogEntryPropertyFilter] | None = None
    date_from: str | None = "-3d"
    date_to: str | None = None
    distinct_ids: list[str] | None = None
    events: list[dict[str, Any]] | None = None
    filter_test_accounts: bool | None = None
    having_predicates: (
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
        | None
    ) = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    operand: FilterLogicalOperator | None = FilterLogicalOperator.AND_
    order: RecordingOrder | None = RecordingOrder.START_TIME
    order_direction: RecordingOrderDirection | None = RecordingOrderDirection.DESC
    person_uuid: str | None = None
    properties: (
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
        | None
    ) = None
    response: RecordingsQueryResponse | None = None
    session_ids: list[str] | None = None
    tags: QueryLogTags | None = None
    user_modified_filters: dict[str, Any] | None = None
    version: float | None = None


@dataclass
class RetentionQueryResponse(SchemaModel):
    results: list[RetentionResult]
    error: str | None = None
    hogql: str | None = None
    modifiers: HogQLQueryModifiers | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class StickinessQuery(SchemaModel):
    kind: Literal["StickinessQuery"] = "StickinessQuery"
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]]
    compareFilter: CompareFilter | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    interval: IntervalType | None = IntervalType.DAY
    intervalCount: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: StickinessQueryResponse | None = None
    samplingFactor: float | None = None
    stickinessFilter: StickinessFilter | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class TeamTaxonomyQuery(SchemaModel):
    kind: Literal["TeamTaxonomyQuery"] = "TeamTaxonomyQuery"
    modifiers: HogQLQueryModifiers | None = None
    response: TeamTaxonomyQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class TrendsQuery(SchemaModel):
    kind: Literal["TrendsQuery"] = "TrendsQuery"
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]]
    aggregation_group_type_index: int | None = None
    breakdownFilter: BreakdownFilter | None = None
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    interval: IntervalType | None = IntervalType.DAY
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: TrendsQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    trendsFilter: TrendsFilter | None = None
    version: float | None = None


@dataclass
class VectorSearchQuery(SchemaModel):
    embedding: list[float]
    kind: Literal["VectorSearchQuery"] = "VectorSearchQuery"
    embeddingVersion: float | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: VectorSearchQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class WebTrendsQuery(SchemaModel):
    interval: IntervalType
    kind: Literal["WebTrendsQuery"] = "WebTrendsQuery"
    metrics: list[WebTrendsMetric]
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebTrendsQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class WebVitalsPathBreakdownQuery(SchemaModel):
    kind: Literal["WebVitalsPathBreakdownQuery"] = "WebVitalsPathBreakdownQuery"
    metric: WebVitalsMetric
    percentile: WebVitalsPercentile
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    thresholds: list[float]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebVitalsPathBreakdownQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class CachedErrorTrackingIssueCorrelationQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    results: list[ErrorTrackingCorrelatedIssue]
    timezone: str
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class CachedExperimentTrendsQueryResponse(SchemaModel):
    cache_key: str
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    is_cached: bool
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    last_refresh: str
    next_allowed_client_refresh: str
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    timezone: str
    variants: list[ExperimentVariantTrendsBaseStats]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    count_query: TrendsQuery | None = None
    exposure_query: TrendsQuery | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    stats_version: int | None = None


@dataclass
class CalendarHeatmapQuery(SchemaModel):
    kind: Literal["CalendarHeatmapQuery"] = "CalendarHeatmapQuery"
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]]
    aggregation_group_type_index: int | None = None
    calendarHeatmapFilter: CalendarHeatmapFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    interval: IntervalType | None = IntervalType.DAY
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: CalendarHeatmapResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class Response19(SchemaModel):
    results: list[ErrorTrackingCorrelatedIssue]
    columns: list[str] | None = None
    error: str | None = None
    hasMore: bool | None = None
    hogql: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    query_status: QueryStatus | None = None
    resolved_date_range: ResolvedDateRangeResponse | None = None
    timings: list[QueryTiming] | None = None


@dataclass
class Response21(SchemaModel):
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantTrendsBaseStats]
    count_query: TrendsQuery | None = None
    exposure_query: TrendsQuery | None = None
    stats_version: int | None = None


@dataclass
class DataVisualizationNode(SchemaModel):
    kind: Literal["DataVisualizationNode"] = "DataVisualizationNode"
    source: HogQLQuery
    chartSettings: ChartSettings | None = None
    display: ChartDisplayType | None = None
    tableSettings: TableSettings | None = None
    version: float | None = None


@dataclass
class DatabaseSchemaManagedViewTable(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    id: str
    kind: DatabaseSchemaManagedViewTableKind
    name: str
    query: HogQLQuery
    type: Literal["managed_view"] = "managed_view"
    row_count: float | None = None
    source_id: str | None = None


@dataclass
class DatabaseSchemaMaterializedViewTable(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    query: HogQLQuery
    type: Literal["materialized_view"] = "materialized_view"
    last_run_at: str | None = None
    row_count: float | None = None
    status: str | None = None


@dataclass
class DatabaseSchemaViewTable(SchemaModel):
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    query: HogQLQuery
    type: Literal["view"] = "view"
    row_count: float | None = None


@dataclass
class ErrorTrackingIssueCorrelationQuery(SchemaModel):
    events: list[str]
    kind: Literal["ErrorTrackingIssueCorrelationQuery"] = "ErrorTrackingIssueCorrelationQuery"
    modifiers: HogQLQueryModifiers | None = None
    response: ErrorTrackingIssueCorrelationQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class ErrorTrackingQuery(SchemaModel):
    dateRange: DateRange
    kind: Literal["ErrorTrackingQuery"] = "ErrorTrackingQuery"
    volumeResolution: int
    assignee: ErrorTrackingIssueAssignee | None = None
    filterGroup: PropertyGroupFilter | None = None
    filterTestAccounts: bool | None = None
    issueId: str | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: OrderBy | None = None
    orderDirection: OrderDirection | None = None
    response: ErrorTrackingQueryResponse | None = None
    searchQuery: str | None = None
    status: Status2 | None = None
    tags: QueryLogTags | None = None
    version: float | None = None
    withAggregations: bool | None = None
    withFirstEvent: bool | None = None
    withLastEvent: bool | None = None


@dataclass
class ExperimentFunnelMetric(SchemaModel):
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    metric_type: Literal["funnel"] = "funnel"
    series: list[Union[EventsNode, ActionsNode]]
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    fingerprint: str | None = None
    funnel_order_type: StepOrderValue | None = None
    goal: ExperimentMetricGoal | None = None
    name: str | None = None
    response: dict[str, Any] | None = None
    uuid: str | None = None
    version: float | None = None


@dataclass
class ExperimentMeanMetric(SchemaModel):
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    metric_type: Literal["mean"] = "mean"
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    fingerprint: str | None = None
    goal: ExperimentMetricGoal | None = None
    ignore_zeros: bool | None = None
    lower_bound_percentile: float | None = None
    name: str | None = None
    response: dict[str, Any] | None = None
    upper_bound_percentile: float | None = None
    uuid: str | None = None
    version: float | None = None


@dataclass
class ExperimentMeanMetricTypeProps(SchemaModel):
    metric_type: Literal["mean"] = "mean"
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    ignore_zeros: bool | None = None
    lower_bound_percentile: float | None = None
    upper_bound_percentile: float | None = None


ExperimentMetric = Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]


ExperimentMetricTypeProps = Union[
    ExperimentMeanMetricTypeProps, ExperimentFunnelMetricTypeProps, ExperimentRatioMetricTypeProps
]


@dataclass
class ExperimentQueryResponse(SchemaModel):
    baseline: ExperimentStatsBaseValidated | None = None
    credible_intervals: dict[str, list[float]] | None = None
    insight: list[dict[str, Any]] | None = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric] | None = None
    p_value: float | None = None
    probability: dict[str, float] | None = None
    significance_code: ExperimentSignificanceCode | None = None
    significant: bool | None = None
    stats_version: int | None = None
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]] | None = (
        None
    )
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]] | None = None


@dataclass
class ExperimentTrendsQueryResponse(SchemaModel):
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantTrendsBaseStats]
    count_query: TrendsQuery | None = None
    exposure_query: TrendsQuery | None = None
    stats_version: int | None = None


@dataclass
class FunnelsQuery(SchemaModel):
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]]
    aggregation_group_type_index: int | None = None
    breakdownFilter: BreakdownFilter | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    funnelsFilter: FunnelsFilter | None = None
    interval: IntervalType | None = None
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: FunnelsQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightsQueryBaseCalendarHeatmapResponse(SchemaModel):
    kind: NodeKind
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: CalendarHeatmapResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightsQueryBaseFunnelsQueryResponse(SchemaModel):
    kind: NodeKind
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: FunnelsQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightsQueryBaseLifecycleQueryResponse(SchemaModel):
    kind: NodeKind
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: LifecycleQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightsQueryBasePathsQueryResponse(SchemaModel):
    kind: NodeKind
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: PathsQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightsQueryBaseRetentionQueryResponse(SchemaModel):
    kind: NodeKind
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: RetentionQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightsQueryBaseTrendsQueryResponse(SchemaModel):
    kind: NodeKind
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: TrendsQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class LegacyExperimentQueryResponse(SchemaModel):
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]
    stats_version: int | None = None


@dataclass
class LifecycleQuery(SchemaModel):
    kind: Literal["LifecycleQuery"] = "LifecycleQuery"
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]]
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    interval: IntervalType | None = IntervalType.DAY
    lifecycleFilter: LifecycleFilter | None = None
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: LifecycleQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class LogsQuery(SchemaModel):
    dateRange: DateRange
    filterGroup: PropertyGroupFilter
    kind: Literal["LogsQuery"] = "LogsQuery"
    serviceNames: list[str]
    severityLevels: list[LogSeverityLevel]
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: OrderBy2 | None = None
    response: LogsQueryResponse | None = None
    searchTerm: str | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class QueryResponseAlternative15(SchemaModel):
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantFunnelsBaseStats]
    funnels_query: FunnelsQuery | None = None
    stats_version: int | None = None


@dataclass
class QueryResponseAlternative16(SchemaModel):
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantTrendsBaseStats]
    count_query: TrendsQuery | None = None
    exposure_query: TrendsQuery | None = None
    stats_version: int | None = None


@dataclass
class QueryResponseAlternative17(SchemaModel):
    baseline: ExperimentStatsBaseValidated | None = None
    credible_intervals: dict[str, list[float]] | None = None
    insight: list[dict[str, Any]] | None = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric] | None = None
    p_value: float | None = None
    probability: dict[str, float] | None = None
    significance_code: ExperimentSignificanceCode | None = None
    significant: bool | None = None
    stats_version: int | None = None
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]] | None = (
        None
    )
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]] | None = None


@dataclass
class QueryResponseAlternative52(SchemaModel):
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantFunnelsBaseStats]
    funnels_query: FunnelsQuery | None = None
    stats_version: int | None = None


@dataclass
class QueryResponseAlternative53(SchemaModel):
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantTrendsBaseStats]
    count_query: TrendsQuery | None = None
    exposure_query: TrendsQuery | None = None
    stats_version: int | None = None


@dataclass
class RetentionQuery(SchemaModel):
    kind: Literal["RetentionQuery"] = "RetentionQuery"
    retentionFilter: RetentionFilter
    aggregation_group_type_index: int | None = None
    breakdownFilter: BreakdownFilter | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: RetentionQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class StickinessActorsQuery(SchemaModel):
    kind: Literal["StickinessActorsQuery"] = "StickinessActorsQuery"
    source: StickinessQuery
    compare: Compare | None = None
    day: Union[str, int] | None = None
    includeRecordings: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    operator: StickinessOperator | None = None
    response: ActorsQueryResponse | None = None
    series: int | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class NamedArgs(SchemaModel):
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]


@dataclass
class IsExperimentFunnelMetric(SchemaModel):
    namedArgs: NamedArgs | None = None


@dataclass
class IsExperimentMeanMetric(SchemaModel):
    namedArgs: NamedArgs | None = None


@dataclass
class IsExperimentRatioMetric(SchemaModel):
    namedArgs: NamedArgs | None = None


@dataclass
class CachedExperimentFunnelsQueryResponse(SchemaModel):
    cache_key: str
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    insight: list[list[dict[str, Any]]]
    is_cached: bool
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    last_refresh: str
    next_allowed_client_refresh: str
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    timezone: str
    variants: list[ExperimentVariantFunnelsBaseStats]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    funnels_query: FunnelsQuery | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    stats_version: int | None = None


@dataclass
class CachedExperimentQueryResponse(SchemaModel):
    cache_key: str
    is_cached: bool
    last_refresh: str
    next_allowed_client_refresh: str
    timezone: str
    baseline: ExperimentStatsBaseValidated | None = None
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    credible_intervals: dict[str, list[float]] | None = None
    insight: list[dict[str, Any]] | None = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric] | None = None
    p_value: float | None = None
    probability: dict[str, float] | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    significance_code: ExperimentSignificanceCode | None = None
    significant: bool | None = None
    stats_version: int | None = None
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]] | None = (
        None
    )
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]] | None = None


@dataclass
class CachedLegacyExperimentQueryResponse(SchemaModel):
    cache_key: str
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    is_cached: bool
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    last_refresh: str
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    next_allowed_client_refresh: str
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    timezone: str
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]
    cache_target_age: str | None = None
    calculation_trigger: str | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = None
    stats_version: int | None = None


@dataclass
class Response20(SchemaModel):
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantFunnelsBaseStats]
    funnels_query: FunnelsQuery | None = None
    stats_version: int | None = None


@dataclass
class ExperimentFunnelsQueryResponse(SchemaModel):
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    variants: list[ExperimentVariantFunnelsBaseStats]
    funnels_query: FunnelsQuery | None = None
    stats_version: int | None = None


@dataclass
class ExperimentMetricTimeseries(SchemaModel):
    computed_at: str | None
    created_at: str
    errors: dict[str, str] | None
    experiment_id: float
    metric_uuid: str
    status: Status5
    timeseries: dict[str, ExperimentQueryResponse] | None
    updated_at: str


@dataclass
class ExperimentQuery(SchemaModel):
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    experiment_id: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    name: str | None = None
    response: ExperimentQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class ExperimentTrendsQuery(SchemaModel):
    count_query: TrendsQuery
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    experiment_id: int | None = None
    exposure_query: TrendsQuery | None = None
    modifiers: HogQLQueryModifiers | None = None
    name: str | None = None
    response: ExperimentTrendsQueryResponse | None = None
    tags: QueryLogTags | None = None
    uuid: str | None = None
    version: float | None = None


@dataclass
class FunnelPathsFilter(SchemaModel):
    funnelSource: FunnelsQuery
    funnelPathType: FunnelPathType | None = None
    funnelStep: int | None = None


@dataclass
class FunnelsActorsQuery(SchemaModel):
    kind: Literal["FunnelsActorsQuery"] = "FunnelsActorsQuery"
    source: FunnelsQuery
    funnelCustomSteps: list[int] | None = None
    funnelStep: int | None = None
    funnelStepBreakdown: Union[int, str, float, list[Union[int, str, float]]] | None = None
    funnelTrendsDropOff: bool | None = None
    funnelTrendsEntrancePeriodStart: str | None = None
    includeRecordings: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: ActorsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class PathsQuery(SchemaModel):
    kind: Literal["PathsQuery"] = "PathsQuery"
    pathsFilter: PathsFilter
    aggregation_group_type_index: int | None = None
    dataColorTheme: float | None = None
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = False
    funnelPathsFilter: FunnelPathsFilter | None = None
    modifiers: HogQLQueryModifiers | None = None
    properties: (
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
        | None
    ) = field(default_factory=lambda: [])
    response: PathsQueryResponse | None = None
    samplingFactor: float | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class QueryResponseAlternative62(SchemaModel):
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
        ],
    ]


QueryResponseAlternative = Union[
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
    QueryResponseAlternative13,
    QueryResponseAlternative14,
    QueryResponseAlternative15,
    QueryResponseAlternative16,
    QueryResponseAlternative17,
    QueryResponseAlternative18,
    QueryResponseAlternative19,
    QueryResponseAlternative20,
    QueryResponseAlternative21,
    QueryResponseAlternative23,
    QueryResponseAlternative24,
    QueryResponseAlternative25,
    QueryResponseAlternative26,
    QueryResponseAlternative27,
    QueryResponseAlternative28,
    QueryResponseAlternative29,
    QueryResponseAlternative30,
    QueryResponseAlternative31,
    Any,
    QueryResponseAlternative32,
    QueryResponseAlternative33,
    QueryResponseAlternative34,
    QueryResponseAlternative35,
    QueryResponseAlternative36,
    QueryResponseAlternative37,
    QueryResponseAlternative38,
    QueryResponseAlternative40,
    QueryResponseAlternative41,
    QueryResponseAlternative42,
    QueryResponseAlternative43,
    QueryResponseAlternative44,
    QueryResponseAlternative45,
    QueryResponseAlternative46,
    QueryResponseAlternative47,
    QueryResponseAlternative49,
    QueryResponseAlternative50,
    QueryResponseAlternative52,
    QueryResponseAlternative53,
    QueryResponseAlternative54,
    QueryResponseAlternative55,
    QueryResponseAlternative56,
    QueryResponseAlternative57,
    QueryResponseAlternative58,
    QueryResponseAlternative59,
    QueryResponseAlternative61,
    QueryResponseAlternative62,
    QueryResponseAlternative63,
    QueryResponseAlternative64,
    QueryResponseAlternative65,
    QueryResponseAlternative66,
    QueryResponseAlternative67,
    QueryResponseAlternative68,
    QueryResponseAlternative70,
]


@dataclass
class VisualizationItem(SchemaModel):
    answer: Union[
        Union[AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, AssistantHogQLQuery],
        Union[TrendsQuery, FunnelsQuery, RetentionQuery, HogQLQuery],
    ]
    initiator: str | None = None
    plan: str | None = None
    query: str | None = ""


@dataclass
class VisualizationMessage(SchemaModel):
    answer: Union[
        Union[AssistantTrendsQuery, AssistantFunnelsQuery, AssistantRetentionQuery, AssistantHogQLQuery],
        Union[TrendsQuery, FunnelsQuery, RetentionQuery, HogQLQuery],
    ]
    type: Literal["ai/viz"] = "ai/viz"
    id: str | None = None
    initiator: str | None = None
    plan: str | None = None
    query: str | None = ""
    short_id: str | None = None


@dataclass
class DatabaseSchemaQueryResponse(SchemaModel):
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
        ],
    ]


@dataclass
class ExperimentFunnelsQuery(SchemaModel):
    funnels_query: FunnelsQuery
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    experiment_id: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    name: str | None = None
    response: ExperimentFunnelsQueryResponse | None = None
    tags: QueryLogTags | None = None
    uuid: str | None = None
    version: float | None = None


@dataclass
class FunnelCorrelationQuery(SchemaModel):
    funnelCorrelationType: FunnelCorrelationResultsType
    kind: Literal["FunnelCorrelationQuery"] = "FunnelCorrelationQuery"
    source: FunnelsActorsQuery
    funnelCorrelationEventExcludePropertyNames: list[str] | None = None
    funnelCorrelationEventNames: list[str] | None = None
    funnelCorrelationExcludeEventNames: list[str] | None = None
    funnelCorrelationExcludeNames: list[str] | None = None
    funnelCorrelationNames: list[str] | None = None
    response: FunnelCorrelationResponse | None = None
    version: float | None = None


@dataclass
class InsightVizNode(SchemaModel):
    kind: Literal["InsightVizNode"] = "InsightVizNode"
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery]
    embedded: bool | None = None
    full: bool | None = None
    hidePersonsModal: bool | None = None
    hideTooltipOnScroll: bool | None = None
    showCorrelationTable: bool | None = None
    showFilters: bool | None = None
    showHeader: bool | None = None
    showLastComputation: bool | None = None
    showLastComputationRefresh: bool | None = None
    showResults: bool | None = None
    showTable: bool | None = None
    suppressSessionAnalysisWarning: bool | None = None
    version: float | None = None
    vizSpecificOptions: VizSpecificOptions | None = None


@dataclass
class MultiVisualizationMessage(SchemaModel):
    type: Literal["ai/multi_viz"] = "ai/multi_viz"
    visualizations: list[VisualizationItem]
    commentary: str | None = None
    id: str | None = None


@dataclass
class NamedQueryRequest(SchemaModel):
    description: str | None = None
    is_active: bool | None = None
    name: str | None = None
    query: (
        Union[HogQLQuery, Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery]]
        | None
    ) = None


@dataclass
class WebVitalsQuery(SchemaModel):
    kind: Literal["WebVitalsQuery"] = "WebVitalsQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery]
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    response: WebGoalsQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = None


@dataclass
class DatabaseSchemaQuery(SchemaModel):
    kind: Literal["DatabaseSchemaQuery"] = "DatabaseSchemaQuery"
    modifiers: HogQLQueryModifiers | None = None
    response: DatabaseSchemaQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class FunnelCorrelationActorsQuery(SchemaModel):
    kind: Literal["FunnelCorrelationActorsQuery"] = "FunnelCorrelationActorsQuery"
    source: FunnelCorrelationQuery
    funnelCorrelationPersonConverted: bool | None = None
    funnelCorrelationPersonEntity: Union[EventsNode, ActionsNode, DataWarehouseNode] | None = None
    funnelCorrelationPropertyValues: (
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
        | None
    ) = None
    includeRecordings: bool | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: ActorsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightActorsQuery(SchemaModel):
    kind: Literal["InsightActorsQuery"] = "InsightActorsQuery"
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery]
    breakdown: Union[str, list[str], int] | None = None
    compare: Compare | None = None
    day: Union[str, int] | None = None
    includeRecordings: bool | None = None
    interval: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: ActorsQueryResponse | None = None
    series: int | None = None
    status: str | None = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class InsightActorsQueryOptions(SchemaModel):
    kind: Literal["InsightActorsQueryOptions"] = "InsightActorsQueryOptions"
    source: Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery]
    response: InsightActorsQueryOptionsResponse | None = None
    version: float | None = None


@dataclass
class SessionBatchEventsQuery(SchemaModel):
    kind: Literal["SessionBatchEventsQuery"] = "SessionBatchEventsQuery"
    select: list[str]
    session_ids: list[str]
    actionId: int | None = None
    after: str | None = None
    before: str | None = None
    event: str | None = None
    filterTestAccounts: bool | None = None
    fixedProperties: (
        list[
            Union[
                PropertyGroupFilter,
                PropertyGroupFilterValue,
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
                ],
            ]
        ]
        | None
    ) = None
    group_by_session: bool | None = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: list[str] | None = None
    personId: str | None = None
    properties: (
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
        | None
    ) = None
    response: SessionBatchEventsQueryResponse | None = None
    source: InsightActorsQuery | None = None
    tags: QueryLogTags | None = None
    version: float | None = None
    where: list[str] | None = None


@dataclass
class ActorsQuery(SchemaModel):
    kind: Literal["ActorsQuery"] = "ActorsQuery"
    fixedProperties: (
        list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]] | None
    ) = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: list[str] | None = None
    properties: (
        Union[
            list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]],
            PropertyGroupFilterValue,
        ]
        | None
    ) = None
    response: ActorsQueryResponse | None = None
    search: str | None = None
    select: list[str] | None = None
    source: (
        Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery, HogQLQuery]
        | None
    ) = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class EventsQuery(SchemaModel):
    kind: Literal["EventsQuery"] = "EventsQuery"
    select: list[str]
    actionId: int | None = None
    after: str | None = None
    before: str | None = None
    event: str | None = None
    filterTestAccounts: bool | None = None
    fixedProperties: (
        list[
            Union[
                PropertyGroupFilter,
                PropertyGroupFilterValue,
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
                ],
            ]
        ]
        | None
    ) = None
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = None
    offset: int | None = None
    orderBy: list[str] | None = None
    personId: str | None = None
    properties: (
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
        | None
    ) = None
    response: EventsQueryResponse | None = None
    source: InsightActorsQuery | None = None
    tags: QueryLogTags | None = None
    version: float | None = None
    where: list[str] | None = None


HasPropertiesNode = Union[EventsNode, EventsQuery, PersonsNode]


@dataclass
class DataTableNode(SchemaModel):
    kind: Literal["DataTableNode"] = "DataTableNode"
    source: Union[
        EventsNode,
        EventsQuery,
        PersonsNode,
        ActorsQuery,
        GroupsQuery,
        HogQLQuery,
        WebOverviewQuery,
        WebStatsTableQuery,
        WebExternalClicksTableQuery,
        WebGoalsQuery,
        WebVitalsQuery,
        WebVitalsPathBreakdownQuery,
        SessionAttributionExplorerQuery,
        RevenueAnalyticsGrossRevenueQuery,
        RevenueAnalyticsMetricsQuery,
        RevenueAnalyticsMRRQuery,
        RevenueAnalyticsOverviewQuery,
        RevenueAnalyticsTopCustomersQuery,
        RevenueExampleEventsQuery,
        RevenueExampleDataWarehouseTablesQuery,
        MarketingAnalyticsTableQuery,
        ErrorTrackingQuery,
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        TracesQuery,
        TraceQuery,
    ]
    allowSorting: bool | None = None
    columns: list[str] | None = None
    context: DataTableNodeViewPropsContext | None = None
    embedded: bool | None = None
    expandable: bool | None = None
    full: bool | None = None
    hiddenColumns: list[str] | None = None
    pinnedColumns: list[str] | None = None
    propertiesViaUrl: bool | None = None
    response: (
        Union[
            dict[str, Any],
            Response,
            Response1,
            Response2,
            Response3,
            Response4,
            Response5,
            Response6,
            Response8,
            Response9,
            Response10,
            Response11,
            Response12,
            Response13,
            Response14,
            Response15,
            Response17,
            Response18,
            Response19,
            Response20,
            Response21,
            Response22,
        ]
        | None
    ) = None
    showActions: bool | None = None
    showColumnConfigurator: bool | None = None
    showDateRange: bool | None = None
    showElapsedTime: bool | None = None
    showEventFilter: bool | None = None
    showExport: bool | None = None
    showHogQLEditor: bool | None = None
    showOpenEditorButton: bool | None = None
    showPersistentColumnConfigurator: bool | None = None
    showPropertyFilter: Union[bool, list[TaxonomicFilterGroupType]] | None = None
    showReload: bool | None = None
    showResultsTable: bool | None = None
    showSavedFilters: bool | None = None
    showSavedQueries: bool | None = None
    showSearch: bool | None = None
    showTestAccountFilters: bool | None = None
    showTimings: bool | None = None
    version: float | None = None


@dataclass
class HogQLAutocomplete(SchemaModel):
    endPosition: int
    kind: Literal["HogQLAutocomplete"] = "HogQLAutocomplete"
    language: HogLanguage
    query: str
    startPosition: int
    filters: HogQLFilters | None = None
    globals: dict[str, Any] | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: HogQLAutocompleteResponse | None = None
    sourceQuery: (
        Union[
            EventsNode,
            ActionsNode,
            PersonsNode,
            EventsQuery,
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
            ErrorTrackingIssueCorrelationQuery,
            LogsQuery,
            ExperimentFunnelsQuery,
            ExperimentTrendsQuery,
            CalendarHeatmapQuery,
            RecordingsQuery,
            TracesQuery,
            TraceQuery,
            VectorSearchQuery,
        ]
        | None
    ) = None
    tags: QueryLogTags | None = None
    version: float | None = None


@dataclass
class HogQLMetadata(SchemaModel):
    kind: Literal["HogQLMetadata"] = "HogQLMetadata"
    language: HogLanguage
    query: str
    debug: bool | None = None
    filters: HogQLFilters | None = None
    globals: dict[str, Any] | None = None
    modifiers: HogQLQueryModifiers | None = None
    response: HogQLMetadataResponse | None = None
    sourceQuery: (
        Union[
            EventsNode,
            ActionsNode,
            PersonsNode,
            EventsQuery,
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
            ErrorTrackingIssueCorrelationQuery,
            LogsQuery,
            ExperimentFunnelsQuery,
            ExperimentTrendsQuery,
            CalendarHeatmapQuery,
            RecordingsQuery,
            TracesQuery,
            TraceQuery,
            VectorSearchQuery,
        ]
        | None
    ) = None
    tags: QueryLogTags | None = None
    variables: dict[str, HogQLVariable] | None = None
    version: float | None = None


@dataclass
class HumanMessage(SchemaModel):
    content: str
    type: Literal["human"] = "human"
    id: str | None = None
    ui_context: MaxUIContext | None = None


@dataclass
class MaxDashboardContext(SchemaModel):
    filters: DashboardFilter
    id: float
    insights: list[MaxInsightContext]
    type: Literal["dashboard"] = "dashboard"
    description: str | None = None
    name: str | None = None


@dataclass
class MaxInsightContext(SchemaModel):
    id: str
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
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
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
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
    ]
    type: Literal["insight"] = "insight"
    description: str | None = None
    filtersOverride: DashboardFilter | None = None
    name: str | None = None
    variablesOverride: dict[str, HogQLVariable] | None = None


@dataclass
class MaxUIContext(SchemaModel):
    actions: list[MaxActionContext] | None = None
    dashboards: list[MaxDashboardContext] | None = None
    events: list[MaxEventContext] | None = None
    insights: list[MaxInsightContext] | None = None


@dataclass
class QueryRequest(SchemaModel):
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
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
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
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
    ]
    async_: bool | None = None
    client_query_id: str | None = None
    filters_override: DashboardFilter | None = None
    name: str | None = None
    refresh: RefreshType | None = RefreshType.BLOCKING
    variables_override: dict[str, dict[str, Any]] | None = None


QuerySchemaRoot = Union[
    EventsNode,
    ActionsNode,
    PersonsNode,
    DataWarehouseNode,
    EventsQuery,
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
    ErrorTrackingIssueCorrelationQuery,
    ExperimentFunnelsQuery,
    ExperimentTrendsQuery,
    ExperimentQuery,
    ExperimentExposureQuery,
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
]


@dataclass
class QueryUpgradeRequest(SchemaModel):
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
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
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
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
    ]


@dataclass
class QueryUpgradeResponse(SchemaModel):
    query: Union[
        EventsNode,
        ActionsNode,
        PersonsNode,
        DataWarehouseNode,
        EventsQuery,
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
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        ExperimentQuery,
        ExperimentExposureQuery,
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
    ]


RootAssistantMessage = Union[
    VisualizationMessage,
    MultiVisualizationMessage,
    ReasoningMessage,
    AssistantMessage,
    HumanMessage,
    FailureMessage,
    NotebookUpdateMessage,
    PlanningMessage,
    TaskExecutionMessage,
    RootAssistantMessage1,
]


@dataclass
class SourceConfig(SchemaModel):
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
    iconPath: str
    name: ExternalDataSourceType
    betaSource: bool | None = None
    caption: Union[str, Any] | None = None
    disabledReason: str | None = None
    docsUrl: str | None = None
    existingSource: bool | None = None
    featureFlag: str | None = None
    label: str | None = None
    unreleasedSource: bool | None = None


@dataclass
class Option(SchemaModel):
    label: str
    value: str
    fields: (
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
        | None
    ) = None


@dataclass
class SourceFieldSelectConfig(SchemaModel):
    defaultValue: str
    label: str
    name: str
    options: list[Option]
    required: bool
    type: Literal["select"] = "select"
    converter: SourceFieldSelectConfigConverter | None = None


@dataclass
class SourceFieldSwitchGroupConfig(SchemaModel):
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
    caption: str | None = None
