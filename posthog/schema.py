# mypy: disable-error-code="assignment"

from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel


class SchemaRoot(RootModel[Any]):
    root: Any


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


class AssistantBaseMultipleBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str = Field(..., description="Property name from the plan to break down by.")


class AssistantDateRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: str = Field(..., description="ISO8601 date string.")
    date_to: Optional[str] = Field(default=None, description="ISO8601 date string.")


class AssistantDateTimePropertyFilterOperator(StrEnum):
    IS_DATE_EXACT = "is_date_exact"
    IS_DATE_BEFORE = "is_date_before"
    IS_DATE_AFTER = "is_date_after"


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
    UPDATE = "update"


class AssistantFormOption(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: str
    variant: Optional[str] = None


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


class AssistantGenericMultipleBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str = Field(..., description="Property name from the plan to break down by.")
    type: AssistantEventMultipleBreakdownFilterType


class AssistantGenericPropertyFilterType(StrEnum):
    EVENT = "event"
    PERSON = "person"
    SESSION = "session"
    FEATURE = "feature"


class AssistantHogQLQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    query: str = Field(
        ...,
        description="SQL SELECT statement to execute. Mostly standard ClickHouse SQL with PostHog-specific additions.",
    )


class AssistantMessageType(StrEnum):
    HUMAN = "human"
    TOOL = "tool"
    CONTEXT = "context"
    AI = "ai"
    AI_REASONING = "ai/reasoning"
    AI_VIZ = "ai/viz"
    AI_MULTI_VIZ = "ai/multi_viz"
    AI_FAILURE = "ai/failure"
    AI_NOTEBOOK = "ai/notebook"
    AI_PLANNING = "ai/planning"
    AI_TASK_EXECUTION = "ai/task_execution"


class AssistantNavigateUrl(StrEnum):
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


class AssistantTool(StrEnum):
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
    SESSION_SUMMARIZATION = "session_summarization"
    CREATE_DASHBOARD = "create_dashboard"
    EDIT_CURRENT_DASHBOARD = "edit_current_dashboard"
    READ_TAXONOMY = "read_taxonomy"
    SEARCH = "search"
    READ_DATA = "read_data"
    TODO_WRITE = "todo_write"
    FILTER_REVENUE_ANALYTICS = "filter_revenue_analytics"
    CREATE_FEATURE_FLAG = "create_feature_flag"


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


class AssistantTrendsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregationAxisFormat: Optional[AggregationAxisFormat] = Field(
        default=AggregationAxisFormat.NUMERIC,
        description=(
            "Formats the trends value axis. Do not use the formatting unless you are absolutely sure that formatting"
            " will match the data. `numeric` - no formatting. Prefer this option by default. `duration` - formats the"
            " value in seconds to a human-readable duration, e.g., `132` becomes `2 minutes 12 seconds`. Use this"
            " option only if you are sure that the values are in seconds. `duration_ms` - formats the value in"
            " miliseconds to a human-readable duration, e.g., `1050` becomes `1 second 50 milliseconds`. Use this"
            " option only if you are sure that the values are in miliseconds. `percentage` - adds a percentage sign to"
            " the value, e.g., `50` becomes `50%`. `percentage_scaled` - formats the value as a percentage scaled to"
            " 0-100, e.g., `0.5` becomes `50%`. `currency` - formats the value as a currency, e.g., `1000` becomes"
            " `$1,000`."
        ),
    )
    aggregationAxisPostfix: Optional[str] = Field(
        default=None,
        description=(
            "Custom postfix to add to the aggregation axis, e.g., ` clicks` to format 5 as `5 clicks`. You may need to"
            " add a space before postfix."
        ),
    )
    aggregationAxisPrefix: Optional[str] = Field(
        default=None,
        description=(
            "Custom prefix to add to the aggregation axis, e.g., `$` for USD dollars. You may need to add a space after"
            " prefix."
        ),
    )
    decimalPlaces: Optional[float] = Field(
        default=None,
        description=(
            "Number of decimal places to show. Do not add this unless you are sure that values will have a decimal"
            " point."
        ),
    )
    display: Optional[Display] = Field(
        default=Display.ACTIONS_LINE_GRAPH,
        description=(
            "Visualization type. Available values: `ActionsLineGraph` - time-series line chart; most common option, as"
            " it shows change over time. `ActionsBar` - time-series bar chart. `ActionsAreaGraph` - time-series area"
            " chart. `ActionsLineGraphCumulative` - cumulative time-series line chart; good for cumulative metrics."
            " `BoldNumber` - total value single large number. Use when user explicitly asks for a single output number."
            " You CANNOT use this with breakdown or if the insight has more than one series. `ActionsBarValue` - total"
            " value (NOT time-series) bar chart; good for categorical data. `ActionsPie` - total value pie chart; good"
            " for visualizing proportions. `ActionsTable` - total value table; good when using breakdown to list users"
            " or other entities. `WorldMap` - total value world map; use when breaking down by country name using"
            " property `$geoip_country_name`, and only then."
        ),
    )
    formulas: Optional[list[str]] = Field(
        default=None,
        description=(
            "If the math aggregation is more complex or not listed above, use custom formulas to perform mathematical"
            " operations like calculating percentages or metrics. If you use a formula, you must use the following"
            " syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and"
            " formulas. When using a formula, you must:\n- Identify and specify **all** events and actions needed to"
            " solve the formula.\n- Carefully review the list of available events and actions to find appropriate"
            " entities for each part of the formula.\n- Ensure that you find events and actions corresponding to both"
            " the numerator and denominator in ratio calculations. Examples of using math formulas:\n- If you want to"
            " calculate the percentage of users who have completed onboarding, you need to find and use events or"
            " actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B`, where `A` is"
            " `onboarding complete` (unique users) and `B` is `$identify` (unique users)."
        ),
    )
    showLegend: Optional[bool] = Field(
        default=False, description="Whether to show the legend describing series and breakdowns."
    )
    showPercentStackView: Optional[bool] = Field(
        default=False, description="Whether to show a percentage of each series. Use only with"
    )
    showValuesOnSeries: Optional[bool] = Field(default=False, description="Whether to show a value on each data point.")
    yAxisScaleType: Optional[YAxisScaleType] = Field(
        default=YAxisScaleType.LINEAR, description="Whether to scale the y-axis."
    )


class AssistantUpdateEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: str
    tool_call_id: str


class AttributionMode(StrEnum):
    FIRST_TOUCH = "first_touch"
    LAST_TOUCH = "last_touch"


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


class BaseAssistantMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None


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


class CalendarHeatmapFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dummy: Optional[str] = None


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


class ChartSettingsDisplay(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    color: Optional[str] = None
    displayType: Optional[DisplayType] = None
    label: Optional[str] = None
    trendLine: Optional[bool] = None
    yAxisPosition: Optional[YAxisPosition] = None


class Style(StrEnum):
    NONE = "none"
    NUMBER = "number"
    PERCENT = "percent"


class ChartSettingsFormatting(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    decimalPlaces: Optional[float] = None
    prefix: Optional[str] = None
    style: Optional[Style] = None
    suffix: Optional[str] = None


class CompareFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[bool] = Field(
        default=False, description="Whether to compare the current date range to a previous date range."
    )
    compare_to: Optional[str] = Field(
        default=None,
        description=(
            "The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1"
            " year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30"
            " hours ago."
        ),
    )


class ColorMode(StrEnum):
    LIGHT = "light"
    DARK = "dark"


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


class CustomEventConversionGoal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class DatabaseSchemaManagedViewTableKind(StrEnum):
    REVENUE_ANALYTICS_CHARGE = "revenue_analytics_charge"
    REVENUE_ANALYTICS_CUSTOMER = "revenue_analytics_customer"
    REVENUE_ANALYTICS_PRODUCT = "revenue_analytics_product"
    REVENUE_ANALYTICS_REVENUE_ITEM = "revenue_analytics_revenue_item"
    REVENUE_ANALYTICS_SUBSCRIPTION = "revenue_analytics_subscription"


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


class DatabaseSchemaTableType(StrEnum):
    POSTHOG = "posthog"
    SYSTEM = "system"
    DATA_WAREHOUSE = "data_warehouse"
    VIEW = "view"
    BATCH_EXPORT = "batch_export"
    MATERIALIZED_VIEW = "materialized_view"
    MANAGED_VIEW = "managed_view"
    ENDPOINT = "endpoint"


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


class DistanceFunc(StrEnum):
    L1_DISTANCE = "L1Distance"
    L2_DISTANCE = "L2Distance"
    COSINE_DISTANCE = "cosineDistance"


class OrderBy(StrEnum):
    DISTANCE = "distance"
    TIMESTAMP = "timestamp"


class OrderDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class DurationType(StrEnum):
    DURATION = "duration"
    ACTIVE_SECONDS = "active_seconds"
    INACTIVE_SECONDS = "inactive_seconds"


class Key(StrEnum):
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


class EmbeddedDocument(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    document_id: str
    document_type: str
    product: str
    timestamp: datetime


class EmbeddingModelName(StrEnum):
    TEXT_EMBEDDING_3_SMALL_1536 = "text-embedding-3-small-1536"
    TEXT_EMBEDDING_3_LARGE_3072 = "text-embedding-3-large-3072"


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


class EmptyPropertyFilter(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class EndpointLastExecutionTimesRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    names: list[str]


class EntityType(StrEnum):
    ACTIONS = "actions"
    EVENTS = "events"
    DATA_WAREHOUSE = "data_warehouse"
    NEW_ENTITY = "new_entity"


class Population(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class FirstEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    properties: str
    timestamp: str
    uuid: str


class LastEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class ErrorTrackingIssueAssigneeType(StrEnum):
    USER = "user"
    ROLE = "role"


class ErrorTrackingIssueCohort(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: float
    name: str


class OrderBy1(StrEnum):
    LAST_SEEN = "last_seen"
    FIRST_SEEN = "first_seen"
    OCCURRENCES = "occurrences"
    USERS = "users"
    SESSIONS = "sessions"
    REVENUE = "revenue"


class OrderDirection1(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class Status2(StrEnum):
    ARCHIVED = "archived"
    ACTIVE = "active"
    RESOLVED = "resolved"
    PENDING_RELEASE = "pending_release"
    SUPPRESSED = "suppressed"
    ALL = "all"


class ErrorTrackingIssueImpactToolOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[str]


class RevenueEntity(StrEnum):
    PERSON = "person"
    GROUP_0 = "group_0"
    GROUP_1 = "group_1"
    GROUP_2 = "group_2"
    GROUP_3 = "group_3"
    GROUP_4 = "group_4"


class RevenuePeriod(StrEnum):
    ALL_TIME = "all_time"
    LAST_30_DAYS = "last_30_days"


class Status4(StrEnum):
    ARCHIVED = "archived"
    ACTIVE = "active"
    RESOLVED = "resolved"
    PENDING_RELEASE = "pending_release"
    SUPPRESSED = "suppressed"


class EventDefinition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    elements: list
    event: str
    properties: dict[str, Any]


class CorrelationType(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


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


class MultipleVariantHandling(StrEnum):
    EXCLUDE = "exclude"
    FIRST_SEEN = "first_seen"


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


class ExperimentMetricOutlierHandling(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ignore_zeros: Optional[bool] = None
    lower_bound_percentile: Optional[float] = None
    upper_bound_percentile: Optional[float] = None


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


class ExperimentStatsMethod(StrEnum):
    BAYESIAN = "bayesian"
    FREQUENTIST = "frequentist"


class ExperimentStatsValidationFailure(StrEnum):
    NOT_ENOUGH_EXPOSURES = "not-enough-exposures"
    BASELINE_MEAN_IS_ZERO = "baseline-mean-is-zero"
    NOT_ENOUGH_METRIC_DATA = "not-enough-metric-data"


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


class ExternalDataSourceType(StrEnum):
    CUSTOMER_IO = "CustomerIO"
    GITHUB = "Github"
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
    TIK_TOK_ADS = "TikTokAds"
    SHOPIFY = "Shopify"


class ExternalQueryErrorCode(StrEnum):
    PLATFORM_ACCESS_REQUIRED = "platform_access_required"
    QUERY_EXECUTION_FAILED = "query_execution_failed"


class ExternalQueryStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class FailureMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: Optional[str] = None
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    type: Literal["ai/failure"] = "ai/failure"


class FileSystemCount(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: float


class Tag(StrEnum):
    ALPHA = "alpha"
    BETA = "beta"


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


class FileSystemIconType(StrEnum):
    DEFAULT_ICON_TYPE = "default_icon_type"
    DASHBOARD = "dashboard"
    LLM_ANALYTICS = "llm_analytics"
    PRODUCT_ANALYTICS = "product_analytics"
    REVENUE_ANALYTICS = "revenue_analytics"
    REVENUE_ANALYTICS_METADATA = "revenue_analytics_metadata"
    MARKETING_SETTINGS = "marketing_settings"
    MANAGED_VIEWSETS = "managed_viewsets"
    ENDPOINTS = "endpoints"
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
    FEATURE_FLAG_OFF = "feature_flag_off"
    DATA_PIPELINE = "data_pipeline"
    DATA_PIPELINE_METADATA = "data_pipeline_metadata"
    DATA_WAREHOUSE = "data_warehouse"
    TASK = "task"
    LINK = "link"
    LIVE_DEBUGGER = "live_debugger"
    LOGS = "logs"
    WORKFLOWS = "workflows"
    NOTEBOOK = "notebook"
    ACTION = "action"
    COMMENT = "comment"
    ANNOTATION = "annotation"
    EVENT = "event"
    EVENT_DEFINITION = "event_definition"
    PROPERTY_DEFINITION = "property_definition"
    INGESTION_WARNING = "ingestion_warning"
    PERSONS = "persons"
    USER = "user"
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
    APPS = "apps"
    LIVE = "live"
    CHAT = "chat"


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


class FilterLogicalOperator(StrEnum):
    AND_ = "AND"
    OR_ = "OR"


class FlagPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="The key should be the flag ID")
    label: Optional[str] = None
    operator: Literal["flag_evaluates_to"] = Field(
        default="flag_evaluates_to", description="Only flag_evaluates_to operator is allowed for flag dependencies"
    )
    type: Literal["flag"] = Field(default="flag", description="Feature flag dependency")
    value: Union[bool, str] = Field(..., description="The value can be true, false, or a variant name")


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


class FunnelVizType(StrEnum):
    STEPS = "steps"
    TIME_TO_CONVERT = "time_to_convert"
    TRENDS = "trends"


class GoalLine(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    borderColor: Optional[str] = None
    displayIfCrossed: Optional[bool] = None
    displayLabel: Optional[bool] = None
    label: str
    value: float


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


class HogCompileResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class HogQLVariable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code_name: str
    isNull: Optional[bool] = None
    value: Optional[Any] = None
    variableId: str


class HogQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: Optional[list] = None
    coloredBytecode: Optional[list] = None
    results: Any
    stdout: Optional[str] = None


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


class InsightsThresholdBounds(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lower: Optional[float] = None
    upper: Optional[float] = None


class IntegrationFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    integrationSourceIds: Optional[list[str]] = Field(
        default=None, description="Selected integration source IDs to filter by (e.g., table IDs or source map IDs)"
    )


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
    GITLAB = "gitlab"
    META_ADS = "meta-ads"
    CLICKUP = "clickup"
    REDDIT_ADS = "reddit-ads"
    DATABRICKS = "databricks"
    TIKTOK_ADS = "tiktok-ads"


class IntervalType(StrEnum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


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


class OrderBy3(StrEnum):
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


class MaxBillingContextBillingPeriodInterval(StrEnum):
    MONTH = "month"
    YEAR = "year"


class MaxBillingContextSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active_destinations: float
    autocapture_on: bool


class MaxBillingContextSubscriptionLevel(StrEnum):
    FREE = "free"
    PAID = "paid"
    CUSTOM = "custom"


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


class MultipleBreakdownType(StrEnum):
    COHORT = "cohort"
    PERSON = "person"
    EVENT = "event"
    EVENT_METADATA = "event_metadata"
    GROUP = "group"
    SESSION = "session"
    HOGQL = "hogql"
    REVENUE_ANALYTICS = "revenue_analytics"


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
    ERROR_TRACKING_SIMILAR_ISSUES_QUERY = "ErrorTrackingSimilarIssuesQuery"
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
    MARKETING_ANALYTICS_AGGREGATED_QUERY = "MarketingAnalyticsAggregatedQuery"
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
    DOCUMENT_SIMILARITY_QUERY = "DocumentSimilarityQuery"
    USAGE_METRICS_QUERY = "UsageMetricsQuery"


class PageURL(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count: float
    url: str


class PathCleaningFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    alias: Optional[str] = None
    order: Optional[float] = None
    regex: Optional[str] = None


class PathType(StrEnum):
    FIELD_PAGEVIEW = "$pageview"
    FIELD_SCREEN = "$screen"
    CUSTOM_EVENT = "custom_event"
    HOGQL = "hogql"


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


class PlanningStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


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


class PropertyFilterType(StrEnum):
    META = "meta"
    EVENT = "event"
    INTERNAL_EVENT = "internal_event"
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


class Mark(BaseModel):
    attrs: Optional[dict[str, Any]] = None
    type: str


class ProsemirrorJSONContent(BaseModel):
    attrs: Optional[dict[str, Any]] = None
    content: Optional[list[ProsemirrorJSONContent]] = None
    marks: Optional[list[Mark]] = None
    text: Optional[str] = None
    type: Optional[str] = None


class QueryIndexUsage(StrEnum):
    UNDECISIVE = "undecisive"
    NO = "no"
    PARTIAL = "partial"
    YES = "yes"


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


class QueryResponseAlternative6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: Optional[list] = None
    coloredBytecode: Optional[list] = None
    results: Any
    stdout: Optional[str] = None


class QueryResponseAlternative19(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: DateRange
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    timeseries: list[ExperimentExposureTimeSeries]
    total_exposures: dict[str, float]


class QueryResponseAlternative68(BaseModel):
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


class RecordingDurationFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: DurationType
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    value: float


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
    RECORDING_TTL = "recording_ttl"


class RecordingOrderDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class RecordingPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Union[DurationType, str]
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class RefreshType(StrEnum):
    ASYNC_ = "async"
    ASYNC_EXCEPT_ON_CACHE_MISS = "async_except_on_cache_miss"
    BLOCKING = "blocking"
    FORCE_ASYNC = "force_async"
    FORCE_BLOCKING = "force_blocking"
    FORCE_CACHE = "force_cache"
    LAZY_ASYNC = "lazy_async"


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


class ResultCustomizationBy(StrEnum):
    VALUE = "value"
    POSITION = "position"


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


class RetentionDashboardDisplayType(StrEnum):
    TABLE_ONLY = "table_only"
    GRAPH_ONLY = "graph_only"
    ALL = "all"


class RetentionEntityKind(StrEnum):
    ACTIONS_NODE = "ActionsNode"
    EVENTS_NODE = "EventsNode"


class TimeWindowMode(StrEnum):
    STRICT_CALENDAR_DATES = "strict_calendar_dates"
    FIELD_24_HOUR_WINDOWS = "24_hour_windows"


class RetentionPeriod(StrEnum):
    HOUR = "Hour"
    DAY = "Day"
    WEEK = "Week"
    MONTH = "Month"


class RetentionType(StrEnum):
    RETENTION_RECURRING = "retention_recurring"
    RETENTION_FIRST_TIME = "retention_first_time"
    RETENTION_FIRST_EVER_OCCURRENCE = "retention_first_ever_occurrence"


class RevenueAnalyticsBreakdown(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str
    type: Literal["revenue_analytics"] = "revenue_analytics"


class MrrOrGross(StrEnum):
    MRR = "mrr"
    GROSS = "gross"


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


class RevenueAnalyticsOverviewItemKey(StrEnum):
    REVENUE = "revenue"
    PAYING_CUSTOMER_COUNT = "paying_customer_count"
    AVG_REVENUE_PER_CUSTOMER = "avg_revenue_per_customer"


class RevenueAnalyticsPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["revenue_analytics"] = "revenue_analytics"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class RevenueAnalyticsTopCustomersGroupBy(StrEnum):
    MONTH = "month"
    ALL = "all"


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


class SessionAttributionGroupBy(StrEnum):
    CHANNEL_TYPE = "ChannelType"
    MEDIUM = "Medium"
    SOURCE = "Source"
    CAMPAIGN = "Campaign"
    AD_IDS = "AdIds"
    REFERRING_DOMAIN = "ReferringDomain"
    INITIAL_URL = "InitialURL"


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


class SessionPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["session"] = "session"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class SnapshotSource(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    UNKNOWN = "unknown"


class Storage(StrEnum):
    OBJECT_STORAGE_LTS = "object_storage_lts"
    OBJECT_STORAGE = "object_storage"


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
    first_seen: str
    id: str
    library: Optional[str] = None
    name: str
    status: str


class SimpleIntervalType(StrEnum):
    DAY = "day"
    MONTH = "month"


class SourceFieldFileUploadJsonFormatConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class SourceFieldSelectConfigConverter(StrEnum):
    STR_TO_INT = "str_to_int"
    STR_TO_BOOL = "str_to_bool"
    STR_TO_OPTIONAL_INT = "str_to_optional_int"


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


class StepOrderValue(StrEnum):
    STRICT = "strict"
    UNORDERED = "unordered"
    ORDERED = "ordered"


class StickinessComputationMode(StrEnum):
    NON_CUMULATIVE = "non_cumulative"
    CUMULATIVE = "cumulative"


class StickinessFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[bool] = None
    compare_to: Optional[str] = None
    display: Optional[ChartDisplayType] = None
    hidden_legend_keys: Optional[dict[str, Union[bool, Any]]] = None
    show_legend: Optional[bool] = None
    show_multiple_y_axes: Optional[bool] = None
    show_values_on_series: Optional[bool] = None


class StickinessOperator(StrEnum):
    GTE = "gte"
    LTE = "lte"
    EXACT = "exact"


class SubscriptionDropoffMode(StrEnum):
    LAST_EVENT = "last_event"
    AFTER_DROPOFF_PERIOD = "after_dropoff_period"


class SuggestedQuestionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    questions: list[str]


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


class Branching(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    index: Optional[float] = None
    responseValues: Optional[dict[str, Union[str, float]]] = None
    type: SurveyQuestionBranchingType


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
    INTERNAL_EVENTS = "internal_events"
    INTERNAL_EVENT_PROPERTIES = "internal_event_properties"
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
    ACTIVITY_LOG_PROPERTIES = "activity_log_properties"
    MAX_AI_CONTEXT = "max_ai_context"


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


class DetailedResultsAggregationType(StrEnum):
    TOTAL = "total"
    AVERAGE = "average"
    MEDIAN = "median"


class TrendsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_axis_format: Optional[AggregationAxisFormat] = None
    aggregation_axis_postfix: Optional[str] = None
    aggregation_axis_prefix: Optional[str] = None
    breakdown_histogram_bin_count: Optional[float] = None
    compare: Optional[bool] = None
    compare_to: Optional[str] = None
    decimal_places: Optional[float] = None
    display: Optional[ChartDisplayType] = None
    formula: Optional[str] = None
    hidden_legend_keys: Optional[dict[str, Union[bool, Any]]] = None
    min_decimal_places: Optional[float] = None
    show_alert_threshold_lines: Optional[bool] = None
    show_labels_on_series: Optional[bool] = None
    show_legend: Optional[bool] = None
    show_multiple_y_axes: Optional[bool] = None
    show_percent_stack_view: Optional[bool] = None
    show_values_on_series: Optional[bool] = None
    smoothing_intervals: Optional[float] = None
    y_axis_scale_type: Optional[YAxisScaleType] = YAxisScaleType.LINEAR


class TrendsFormulaNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = Field(default=None, description="Optional user-defined name for the formula")
    formula: str


class UsageMetricDisplay(StrEnum):
    NUMBER = "number"
    SPARKLINE = "sparkline"


class UsageMetricFormat(StrEnum):
    NUMERIC = "numeric"
    CURRENCY = "currency"


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


class WebVitalsPathBreakdownResultItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    path: str
    value: float


class WebVitalsPercentile(StrEnum):
    P75 = "p75"
    P90 = "p90"
    P99 = "p99"


class Scale(StrEnum):
    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"


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


class AssistantArrayPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantArrayPropertyFilterOperator = Field(
        ..., description="`exact` - exact match of any of the values. `is_not` - does not match any of the values."
    )
    value: list[str] = Field(
        ...,
        description=(
            "Only use property values from the plan. Always use strings as values. If you have a number, convert it to"
            ' a string first. If you have a boolean, convert it to a string "true" or "false".'
        ),
    )


class AssistantBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_limit: Optional[int] = Field(default=25, description="How many distinct values to show.")


class AssistantDateTimePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantDateTimePropertyFilterOperator
    value: str = Field(..., description="Value must be a date in ISO 8601 format.")


class AssistantForm(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    options: list[AssistantFormOption]


class AssistantFunnelsBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: str = Field(..., description="The entity property to break down by.")
    breakdown_group_type_index: Optional[int] = Field(
        default=None,
        description=(
            "If `breakdown_type` is `group`, this is the index of the group. Use the index from the group mapping."
        ),
    )
    breakdown_limit: Optional[int] = Field(default=25, description="How many distinct values to show.")
    breakdown_type: Optional[AssistantFunnelsBreakdownType] = Field(
        default=AssistantFunnelsBreakdownType.EVENT,
        description=(
            "Type of the entity to break down by. If `group` is used, you must also provide"
            " `breakdown_group_type_index` from the group mapping."
        ),
    )


class AssistantFunnelsExclusionEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    event: str
    funnelFromStep: int
    funnelToStep: int
    kind: Literal["EventsNode"] = "EventsNode"


class AssistantFunnelsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    binCount: Optional[int] = Field(
        default=None,
        description=(
            "Use this setting only when `funnelVizType` is `time_to_convert`: number of bins to show in histogram."
        ),
    )
    exclusions: Optional[list[AssistantFunnelsExclusionEventsNode]] = Field(
        default=[],
        description=(
            "Users may want to use exclusion events to filter out conversions in which a particular event occurred"
            " between specific steps. These events must not be included in the main sequence. This doesn't exclude"
            " users who have completed the event before or after the funnel sequence, but often this is what users"
            " want. (If not sure, worth clarifying.) You must include start and end indexes for each exclusion where"
            " the minimum index is one and the maximum index is the number of steps in the funnel. For example, there"
            " is a sequence with three steps: sign up, finish onboarding, purchase. If the user wants to exclude all"
            " conversions in which users left the page before finishing the onboarding, the exclusion step would be the"
            " event `$pageleave` with start index 2 and end index 3. When exclusion steps appear needed when you're"
            " planning the query, make sure to explicitly state this in the plan."
        ),
    )
    funnelAggregateByHogQL: Optional[FunnelAggregateByHogQL] = Field(
        default=None,
        description="Use this field only if the user explicitly asks to aggregate the funnel by unique sessions.",
    )
    funnelOrderType: Optional[StepOrderValue] = Field(
        default=StepOrderValue.ORDERED,
        description=(
            "Defines the behavior of event matching between steps. Prefer the `strict` option unless explicitly told to"
            " use a different one. `ordered` - defines a sequential funnel. Step B must happen after Step A, but any"
            " number of events can happen between A and B. `strict` - defines a funnel where all events must happen in"
            " order. Step B must happen directly after Step A without any events in between. `any` - order doesn't"
            " matter. Steps can be completed in any sequence."
        ),
    )
    funnelStepReference: Optional[FunnelStepReference] = Field(
        default=FunnelStepReference.TOTAL,
        description=(
            "Whether conversion shown in the graph should be across all steps or just relative to the previous step."
        ),
    )
    funnelVizType: Optional[FunnelVizType] = Field(
        default=FunnelVizType.STEPS,
        description=(
            "Defines the type of visualization to use. The `steps` option is recommended. `steps` - shows a"
            " step-by-step funnel. Perfect to show a conversion rate of a sequence of events (default)."
            " `time_to_convert` - shows a histogram of the time it took to complete the funnel. `trends` - shows trends"
            " of the conversion rate of the whole sequence over time."
        ),
    )
    funnelWindowInterval: Optional[int] = Field(
        default=14,
        description=(
            "Controls a time frame value for a conversion to be considered. Select a reasonable value based on the"
            " user's query. If needed, this can be practically unlimited by setting a large value, though it's rare to"
            " need that. Use in combination with `funnelWindowIntervalUnit`. The default value is 14 days."
        ),
    )
    funnelWindowIntervalUnit: Optional[FunnelConversionWindowTimeUnit] = Field(
        default=FunnelConversionWindowTimeUnit.DAY,
        description=(
            "Controls a time frame interval for a conversion to be considered. Select a reasonable value based on the"
            " user's query. Use in combination with `funnelWindowInterval`. The default value is 14 days."
        ),
    )
    layout: Optional[FunnelLayout] = Field(
        default=FunnelLayout.VERTICAL,
        description="Controls how the funnel chart is displayed: vertically (preferred) or horizontally.",
    )


class AssistantGenerationStatusEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: AssistantGenerationStatusType


class AssistantGenericPropertyFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantStringOrBooleanValuePropertyFilterOperator = Field(
        ...,
        description=(
            "`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` -"
            " matches the regex pattern. `not_regex` - does not match the regex pattern."
        ),
    )
    type: AssistantGenericPropertyFilterType
    value: str = Field(
        ...,
        description=(
            "Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a"
            " valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be"
            " matched against the property value. Use the string values `true` or `false` for boolean properties."
        ),
    )


class AssistantGenericPropertyFilter2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantNumericValuePropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: float


class AssistantGenericPropertyFilter3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantArrayPropertyFilterOperator = Field(
        ..., description="`exact` - exact match of any of the values. `is_not` - does not match any of the values."
    )
    type: AssistantGenericPropertyFilterType
    value: list[str] = Field(
        ...,
        description=(
            "Only use property values from the plan. Always use strings as values. If you have a number, convert it to"
            ' a string first. If you have a boolean, convert it to a string "true" or "false".'
        ),
    )


class AssistantGenericPropertyFilter4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantDateTimePropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: str = Field(..., description="Value must be a date in ISO 8601 format.")


class AssistantGenericPropertyFilter5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantSetPropertyFilterOperator = Field(
        ...,
        description=(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't"
            " collected."
        ),
    )
    type: AssistantGenericPropertyFilterType


class AssistantGroupMultipleBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: Optional[int] = Field(default=None, description="Index of the group type from the group mapping.")
    property: str = Field(..., description="Property name from the plan to break down by.")
    type: Literal["group"] = "group"


class AssistantGroupPropertyFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantStringOrBooleanValuePropertyFilterOperator = Field(
        ...,
        description=(
            "`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` -"
            " matches the regex pattern. `not_regex` - does not match the regex pattern."
        ),
    )
    type: Literal["group"] = "group"
    value: str = Field(
        ...,
        description=(
            "Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a"
            " valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be"
            " matched against the property value. Use the string values `true` or `false` for boolean properties."
        ),
    )


class AssistantGroupPropertyFilter2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantNumericValuePropertyFilterOperator
    type: Literal["group"] = "group"
    value: float


class AssistantGroupPropertyFilter3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantArrayPropertyFilterOperator = Field(
        ..., description="`exact` - exact match of any of the values. `is_not` - does not match any of the values."
    )
    type: Literal["group"] = "group"
    value: list[str] = Field(
        ...,
        description=(
            "Only use property values from the plan. Always use strings as values. If you have a number, convert it to"
            ' a string first. If you have a boolean, convert it to a string "true" or "false".'
        ),
    )


class AssistantGroupPropertyFilter4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantDateTimePropertyFilterOperator
    type: Literal["group"] = "group"
    value: str = Field(..., description="Value must be a date in ISO 8601 format.")


class AssistantGroupPropertyFilter5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantSetPropertyFilterOperator = Field(
        ...,
        description=(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't"
            " collected."
        ),
    )
    type: Literal["group"] = "group"


class AssistantMessageMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    form: Optional[AssistantForm] = None
    thinking: Optional[list[dict[str, Any]]] = None


class AssistantNumericValuePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantNumericValuePropertyFilterOperator
    value: float


class AssistantRetentionActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: float = Field(..., description="Action ID from the plan.")
    name: str = Field(..., description="Action name from the plan.")
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
    ] = Field(default=None, description="Property filters for the action.")
    type: Literal["actions"] = "actions"


class AssistantRetentionEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = Field(
        default=None, description="Custom name for the event if it is needed to be renamed."
    )
    name: str = Field(..., description="Event name from the plan.")
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
    ] = Field(default=None, description="Property filters for the event.")
    type: Literal["events"] = "events"


class AssistantSetPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantSetPropertyFilterOperator = Field(
        ...,
        description=(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't"
            " collected."
        ),
    )


class AssistantStringOrBooleanValuePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantStringOrBooleanValuePropertyFilterOperator = Field(
        ...,
        description=(
            "`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` -"
            " matches the regex pattern. `not_regex` - does not match the regex pattern."
        ),
    )
    value: str = Field(
        ...,
        description=(
            "Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a"
            " valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be"
            " matched against the property value. Use the string values `true` or `false` for boolean properties."
        ),
    )


class AssistantTrendsBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_limit: Optional[int] = Field(default=25, description="How many distinct values to show.")
    breakdowns: list[Union[AssistantGroupMultipleBreakdownFilter, AssistantGenericMultipleBreakdownFilter]] = Field(
        ..., description="Use this field to define breakdowns.", max_length=3
    )


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


class BreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[Union[str, list[Union[str, int]], int]] = None
    breakdown_group_type_index: Optional[int] = None
    breakdown_hide_other_aggregation: Optional[bool] = None
    breakdown_histogram_bin_count: Optional[int] = None
    breakdown_limit: Optional[int] = None
    breakdown_normalize_url: Optional[bool] = None
    breakdown_type: Optional[BreakdownType] = BreakdownType.EVENT
    breakdowns: Optional[list[Breakdown]] = Field(default=None, max_length=3)


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


class CohortPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cohort_name: Optional[str] = None
    key: Literal["id"] = "id"
    label: Optional[str] = None
    operator: Optional[PropertyOperator] = PropertyOperator.IN_
    type: Literal["cohort"] = "cohort"
    value: int


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


class DataWarehousePersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["data_warehouse_person_property"] = "data_warehouse_person_property"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class DataWarehousePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["data_warehouse"] = "data_warehouse"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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


class ElementPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Key
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["element"] = "element"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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


class ErrorTrackingIssueFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["error_tracking_issue"] = "error_tracking_issue"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class EventMetadataPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["event_metadata"] = "event_metadata"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class EventOddsRatioSerialized(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    correlation_type: CorrelationType
    event: EventDefinition
    failure_count: int
    odds_ratio: float
    success_count: int


class EventPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: Optional[PropertyOperator] = PropertyOperator.EXACT
    type: Literal["event"] = Field(default="event", description="Event properties")
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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


class ExperimentExposureQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_range: DateRange
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    timeseries: list[ExperimentExposureTimeSeries]
    total_exposures: dict[str, float]


class ExperimentMetricBaseProperties(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class FeaturePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["feature"] = Field(default="feature", description='Event property with "$feature/" prepended')
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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
    hidden_legend_keys: Optional[dict[str, Union[bool, Any]]] = None
    layout: Optional[FunnelLayout] = None


class GroupPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: Optional[int] = None
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["group"] = "group"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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


class HogQLPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    type: Literal["hogql"] = "hogql"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class LifecycleFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    showLegend: Optional[bool] = False
    showValuesOnSeries: Optional[bool] = None
    stacked: Optional[bool] = True
    toggledLifecycles: Optional[list[LifecycleToggle]] = None


class LifecycleFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    show_legend: Optional[bool] = None
    show_values_on_series: Optional[bool] = None
    toggledLifecycles: Optional[list[LifecycleToggle]] = None


class LogEntryPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["log_entry"] = "log_entry"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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


class LogPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["log"] = "log"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


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
    metrics_results: list[MaxExperimentMetricResult]
    stats_method: ExperimentStatsMethod
    variants: list[str]


class NewExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: ExperimentStatsBaseValidated
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]


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


class PathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    edgeLimit: Optional[int] = 50
    endPoint: Optional[str] = None
    excludeEvents: Optional[list[str]] = None
    includeEventTypes: Optional[list[PathType]] = None
    localPathCleaningFilters: Optional[list[PathCleaningFilter]] = None
    maxEdgeWeight: Optional[int] = None
    minEdgeWeight: Optional[int] = None
    pathDropoffKey: Optional[str] = Field(default=None, description="Relevant only within actors query")
    pathEndKey: Optional[str] = Field(default=None, description="Relevant only within actors query")
    pathGroupings: Optional[list[str]] = None
    pathReplacements: Optional[bool] = None
    pathStartKey: Optional[str] = Field(default=None, description="Relevant only within actors query")
    pathsHogQLExpression: Optional[str] = None
    startPoint: Optional[str] = None
    stepLimit: Optional[int] = 5


class PersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["person"] = Field(default="person", description="Person properties")
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class PlanningStep(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str
    status: PlanningStepStatus


class QueryResponseAlternative8(BaseModel):
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


class QueryResponseAlternative9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incomplete_list: bool = Field(..., description="Whether or not the suggestions returned are complete")
    suggestions: list[AutocompleteCompletionItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative27(BaseModel):
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


class RevenueAnalyticsAssistantFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    properties: list[RevenueAnalyticsPropertyFilter]


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


class RevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
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


class RevenueAnalyticsMRRQueryResponse(BaseModel):
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


class RevenueAnalyticsMetricsQueryResponse(BaseModel):
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


class RevenueAnalyticsOverviewItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: RevenueAnalyticsOverviewItemKey
    value: float


class RevenueAnalyticsOverviewQueryResponse(BaseModel):
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


class RevenueAnalyticsTopCustomersQueryResponse(BaseModel):
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


class RevenueExampleDataWarehouseTablesQueryResponse(BaseModel):
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


class RevenueExampleEventsQueryResponse(BaseModel):
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


class SavedInsightNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    allowSorting: Optional[bool] = Field(
        default=None, description="Can the user click on column headers to sort the table? (default: true)"
    )
    context: Optional[DataTableNodeViewPropsContext] = Field(
        default=None, description="Context for the table, used by components like ColumnConfigurator"
    )
    defaultColumns: Optional[list[str]] = Field(
        default=None, description="Default columns to use when resetting column configuration"
    )
    embedded: Optional[bool] = Field(default=None, description="Query is embedded inside another bordered component")
    expandable: Optional[bool] = Field(
        default=None, description="Can expand row to show raw event data (default: true)"
    )
    full: Optional[bool] = Field(
        default=None, description="Show with most visual options enabled. Used in insight scene."
    )
    hidePersonsModal: Optional[bool] = None
    hideTooltipOnScroll: Optional[bool] = None
    kind: Literal["SavedInsightNode"] = "SavedInsightNode"
    propertiesViaUrl: Optional[bool] = Field(default=None, description="Link properties via the URL (default: false)")
    shortId: str
    showActions: Optional[bool] = Field(default=None, description="Show the kebab menu at the end of the row")
    showColumnConfigurator: Optional[bool] = Field(
        default=None, description="Show a button to configure the table's columns if possible"
    )
    showCorrelationTable: Optional[bool] = None
    showDateRange: Optional[bool] = Field(default=None, description="Show date range selector")
    showElapsedTime: Optional[bool] = Field(default=None, description="Show the time it takes to run a query")
    showEventFilter: Optional[bool] = Field(
        default=None, description="Include an event filter above the table (EventsNode only)"
    )
    showExport: Optional[bool] = Field(default=None, description="Show the export button")
    showFilters: Optional[bool] = None
    showHeader: Optional[bool] = None
    showHogQLEditor: Optional[bool] = Field(default=None, description="Include a HogQL query editor above HogQL tables")
    showLastComputation: Optional[bool] = None
    showLastComputationRefresh: Optional[bool] = None
    showOpenEditorButton: Optional[bool] = Field(
        default=None, description="Show a button to open the current query as a new insight. (default: true)"
    )
    showPersistentColumnConfigurator: Optional[bool] = Field(
        default=None, description="Show a button to configure and persist the table's default columns if possible"
    )
    showPropertyFilter: Optional[Union[bool, list[TaxonomicFilterGroupType]]] = Field(
        default=None, description="Include a property filter above the table"
    )
    showReload: Optional[bool] = Field(default=None, description="Show a reload button")
    showResults: Optional[bool] = None
    showResultsTable: Optional[bool] = Field(default=None, description="Show a results table")
    showSavedFilters: Optional[bool] = Field(
        default=None, description="Show saved filters feature for this table (requires uniqueKey)"
    )
    showSavedQueries: Optional[bool] = Field(default=None, description="Shows a list of saved queries")
    showSearch: Optional[bool] = Field(default=None, description="Include a free text search field (PersonsNode only)")
    showTable: Optional[bool] = None
    showTestAccountFilters: Optional[bool] = Field(default=None, description="Show filter to exclude test accounts")
    showTimings: Optional[bool] = Field(default=None, description="Show a detailed query timing breakdown")
    suppressSessionAnalysisWarning: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    vizSpecificOptions: Optional[VizSpecificOptions] = None


class Filters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    properties: Optional[list[SessionPropertyFilter]] = None


class SessionAttributionExplorerQueryResponse(BaseModel):
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


class SessionBatchEventsQueryResponse(BaseModel):
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
    session_events: Optional[list[SessionEventsItem]] = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    sessions_with_no_events: Optional[list[str]] = Field(
        default=None, description="List of session IDs that had no matching events"
    )
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


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


class SessionsTimelineQueryResponse(BaseModel):
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


class StickinessFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    computedAs: Optional[StickinessComputationMode] = None
    display: Optional[ChartDisplayType] = None
    hiddenLegendIndexes: Optional[list[int]] = None
    resultCustomizationBy: Optional[ResultCustomizationBy] = Field(
        default=ResultCustomizationBy.VALUE,
        description="Whether result datasets are associated by their values or by their order.",
    )
    resultCustomizations: Optional[
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]]
    ] = Field(default=None, description="Customizations for the appearance of result datasets.")
    showLegend: Optional[bool] = None
    showMultipleYAxes: Optional[bool] = None
    showValuesOnSeries: Optional[bool] = None
    stickinessCriteria: Optional[StickinessCriteria] = None


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


class SuggestedQuestionsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["SuggestedQuestionsQuery"] = "SuggestedQuestionsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[SuggestedQuestionsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class TestCachedBasicQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TraceQueryResponse(BaseModel):
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


class TracesQueryResponse(BaseModel):
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


class TrendsAlertConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    check_ongoing_interval: Optional[bool] = None
    series_index: int
    type: Literal["TrendsAlertConfig"] = "TrendsAlertConfig"


class TrendsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregationAxisFormat: Optional[AggregationAxisFormat] = AggregationAxisFormat.NUMERIC
    aggregationAxisPostfix: Optional[str] = None
    aggregationAxisPrefix: Optional[str] = None
    breakdown_histogram_bin_count: Optional[float] = None
    confidenceLevel: Optional[float] = None
    decimalPlaces: Optional[float] = None
    detailedResultsAggregationType: Optional[DetailedResultsAggregationType] = Field(
        default=None, description="detailed results table"
    )
    display: Optional[ChartDisplayType] = ChartDisplayType.ACTIONS_LINE_GRAPH
    formula: Optional[str] = None
    formulaNodes: Optional[list[TrendsFormulaNode]] = Field(
        default=None,
        description="List of formulas with optional custom names. Takes precedence over formula/formulas if set.",
    )
    formulas: Optional[list[str]] = None
    goalLines: Optional[list[GoalLine]] = Field(default=None, description="Goal Lines")
    hiddenLegendIndexes: Optional[list[int]] = None
    minDecimalPlaces: Optional[float] = None
    movingAverageIntervals: Optional[float] = None
    resultCustomizationBy: Optional[ResultCustomizationBy] = Field(
        default=ResultCustomizationBy.VALUE,
        description="Wether result datasets are associated by their values or by their order.",
    )
    resultCustomizations: Optional[
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]]
    ] = Field(default=None, description="Customizations for the appearance of result datasets.")
    showAlertThresholdLines: Optional[bool] = False
    showConfidenceIntervals: Optional[bool] = None
    showLabelsOnSeries: Optional[bool] = None
    showLegend: Optional[bool] = False
    showMovingAverage: Optional[bool] = None
    showMultipleYAxes: Optional[bool] = False
    showPercentStackView: Optional[bool] = False
    showTrendLines: Optional[bool] = None
    showValuesOnSeries: Optional[bool] = False
    smoothingIntervals: Optional[int] = 1
    yAxisScaleType: Optional[YAxisScaleType] = YAxisScaleType.LINEAR


class TrendsQueryResponse(BaseModel):
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


class UsageMetricsQueryResponse(BaseModel):
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


class WebAnalyticsExternalSummaryQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: dict[str, Any]
    error: Optional[ExternalQueryError] = None
    status: ExternalQueryStatus


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


class WebExternalClicksTableQueryResponse(BaseModel):
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


class WebGoalsQueryResponse(BaseModel):
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


class WebOverviewQueryResponse(BaseModel):
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


class WebPageURLSearchQueryResponse(BaseModel):
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


class WebStatsTableQueryResponse(BaseModel):
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


class ActorsPropertyTaxonomyQueryResponse(BaseModel):
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


class ActorsQueryResponse(BaseModel):
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


class AssistantFunnelsActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: float = Field(..., description="Action ID from the plan.")
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[AssistantFunnelsMath] = Field(
        default=None,
        description=(
            "Optional math aggregation type for the series. Only specify this math type if the user wants one of these."
            " `first_time_for_user` - counts the number of users who have completed the event for the first time ever."
            " `first_time_for_user_with_filters` - counts the number of users who have completed the event with"
            " specified filters for the first time."
        ),
    )
    name: str = Field(..., description="Action name from the plan.")
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
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class AssistantFunnelsEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = Field(
        default=None, description="Optional custom name for the event if it is needed to be renamed."
    )
    event: str = Field(..., description="Name of the event.")
    kind: Literal["EventsNode"] = "EventsNode"
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
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class AssistantFunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(
        default=None,
        description=(
            "Use this field to define the aggregation by a specific group from the provided group mapping, which is NOT"
            " users or sessions."
        ),
    )
    breakdownFilter: Optional[AssistantFunnelsBreakdownFilter] = Field(
        default=None,
        description=(
            "A breakdown is used to segment data by a single property value. They divide all defined funnel series into"
            " multiple subseries based on the values of the property. Include a breakdown **only when it is essential"
            " to directly answer the user’s question**. You must not add a breakdown if the question can be addressed"
            " without additional segmentation. When using breakdowns, you must:\n- **Identify the property group** and"
            " name for a breakdown.\n- **Provide the property name** for a breakdown.\n- **Validate that the property"
            " value accurately reflects the intended criteria**. Examples of using a breakdown:\n- page views to sign"
            " up funnel by country: you need to find a property such as `$geoip_country_code` and set it as a"
            " breakdown.\n- conversion rate of users who have completed onboarding after signing up by an organization:"
            " you need to find a property such as `organization name` and set it as a breakdown."
        ),
    )
    dateRange: Optional[Union[AssistantDateRange, AssistantDurationRange]] = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelsFilter: Optional[AssistantFunnelsFilter] = Field(
        default=None, description="Properties specific to the funnels insight"
    )
    interval: Optional[IntervalType] = Field(
        default=None, description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`"
    )
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
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
    series: list[Union[AssistantFunnelsEventsNode, AssistantFunnelsActionsNode]] = Field(
        ..., description="Events or actions to include. Prioritize the more popular and fresh events and actions."
    )


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


class AssistantRetentionFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: Optional[bool] = Field(
        default=None,
        description=(
            "Whether retention should be rolling (aka unbounded, cumulative). Rolling retention means that a user"
            " coming back in period 5 makes them count towards all the previous periods."
        ),
    )
    meanRetentionCalculation: Optional[MeanRetentionCalculation] = Field(
        default=None,
        description=(
            "Whether an additional series should be shown, showing the mean conversion for each period across cohorts."
        ),
    )
    period: Optional[RetentionPeriod] = Field(
        default=RetentionPeriod.DAY, description="Retention period, the interval to track cohorts by."
    )
    retentionReference: Optional[RetentionReference] = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retentionType: Optional[RetentionType] = Field(
        default=None,
        description=(
            "Retention type: recurring or first time. Recurring retention counts a user as part of a cohort if they"
            " performed the cohort event during that time period, irrespective of it was their first time or not. First"
            " time retention only counts a user as part of the cohort if it was their first time performing the cohort"
            " event."
        ),
    )
    returningEntity: Union[AssistantRetentionEventsNode, AssistantRetentionActionsNode] = Field(
        ..., description="Retention event (event marking the user coming back)."
    )
    targetEntity: Union[AssistantRetentionEventsNode, AssistantRetentionActionsNode] = Field(
        ..., description="Activation event (event putting the actor into the initial cohort)."
    )
    totalIntervals: Optional[int] = Field(
        default=11,
        description=(
            "How many intervals to show in the chart. The default value is 11 (meaning 10 periods after initial"
            " cohort)."
        ),
    )


class AssistantRetentionQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[Union[AssistantDateRange, AssistantDurationRange]] = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: Literal["RetentionQuery"] = "RetentionQuery"
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
    retentionFilter: AssistantRetentionFilter = Field(..., description="Properties specific to the retention insight")
    samplingFactor: Optional[float] = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )


class AssistantTrendsActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_type: Optional[str] = None
    name: str = Field(..., description="Action name from the plan.")
    optionalInFunnel: Optional[bool] = None
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
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class AssistantTrendsEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    event: Optional[str] = Field(default=None, description="The event or `null` for all events.")
    kind: Literal["EventsNode"] = "EventsNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class AssistantTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownFilter: Optional[AssistantTrendsBreakdownFilter] = Field(
        default=None,
        description=(
            "Breakdowns are used to segment data by property values of maximum three properties. They divide all"
            " defined trends series to multiple subseries based on the values of the property. Include breakdowns"
            " **only when they are essential to directly answer the user’s question**. You must not add breakdowns if"
            " the question can be addressed without additional segmentation. Always use the minimum set of breakdowns"
            " needed to answer the question. When using breakdowns, you must:\n- **Identify the property group** and"
            " name for each breakdown.\n- **Provide the property name** for each breakdown.\n- **Validate that the"
            " property value accurately reflects the intended criteria**. Examples of using breakdowns:\n- page views"
            " trend by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.\n-"
            " number of users who have completed onboarding by an organization: you need to find a property such as"
            " `organization name` and set it as a breakdown."
        ),
    )
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    dateRange: Optional[Union[AssistantDateRange, AssistantDurationRange]] = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["TrendsQuery"] = "TrendsQuery"
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
    series: list[Union[AssistantTrendsEventsNode, AssistantTrendsActionsNode]] = Field(
        ..., description="Events or actions to include. Prioritize the more popular and fresh events and actions."
    )
    trendsFilter: Optional[AssistantTrendsFilter] = Field(
        default=None, description="Properties specific to the trends insight"
    )


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


class CachedActorsPropertyTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedActorsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int
    missing_actors_count: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: int
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list[str]] = None


class CachedCalendarHeatmapQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = Field(default=None, description="Wether more breakdown values are available.")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: EventsHeatMapStructuredResult
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedDocumentSimilarityQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
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
    results: list[EmbeddingDistance]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedErrorTrackingSimilarIssuesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
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
    results: list[SimilarIssue]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedEventTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EventTaxonomyItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
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
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedExperimentExposureQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    date_range: DateRange
    is_cached: bool
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timeseries: list[ExperimentExposureTimeSeries]
    timezone: str
    total_exposures: dict[str, float]


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


class CachedFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    isUdf: Optional[bool] = None
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedGroupsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    last_refresh: datetime
    limit: int
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: int
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedLifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedLogsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
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
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedMarketingAnalyticsAggregatedQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedMarketingAnalyticsTableQueryResponse(BaseModel):
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
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedNewExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: ExperimentStatsBaseValidated
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timezone: str
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]


class CachedPathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PathsLink]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueExampleDataWarehouseTablesQueryResponse(BaseModel):
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
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedRevenueExampleEventsQueryResponse(BaseModel):
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
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedSessionAttributionExplorerQueryResponse(BaseModel):
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
    results: Any
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedSessionBatchEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: str = Field(..., description="Generated HogQL query.")
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
    results: list[list]
    session_events: Optional[list[SessionEventsItem]] = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    sessions_with_no_events: Optional[list[str]] = Field(
        default=None, description="List of session IDs that had no matching events"
    )
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedSessionsTimelineQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = None
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
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
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedSuggestedQuestionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    questions: list[str]
    timezone: str


class CachedTeamTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TeamTaxonomyItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTraceQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
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
    results: list[LLMTrace]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTracesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
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
    results: list[LLMTrace]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: Optional[bool] = Field(default=None, description="Wether more breakdown values are available.")
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedUsageMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[UsageMetric]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedVectorSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[VectorSearchResponseItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebExternalClicksTableQueryResponse(BaseModel):
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
    results: list
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedWebGoalsQueryResponse(BaseModel):
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
    results: list
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None


class CachedWebOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: Optional[bool] = None


class CachedWebPageURLSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
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
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PageURL]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebStatsTableQueryResponse(BaseModel):
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
    results: list
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = None
    usedPreAggregatedTables: Optional[bool] = None


class CachedWebVitalsPathBreakdownQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


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


class ConversionGoalFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: Optional[str] = None
    event: Optional[str] = Field(default=None, description="The event or `null` for all events.")
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsNode"] = "EventsNode"
    limit: Optional[int] = None
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    schema_map: dict[str, Union[str, Any]]
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ConversionGoalFilter2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: Optional[str] = None
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    schema_map: dict[str, Union[str, Any]]
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ConversionGoalFilter3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: Optional[str] = None
    distinct_id_field: str
    dw_source_type: Optional[str] = None
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    schema_map: dict[str, Union[str, Any]]
    table_name: str
    timestamp_field: str
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class DashboardFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_filter: Optional[BreakdownFilter] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
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
    results: Any
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
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response13(BaseModel):
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


class Response14(BaseModel):
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


class Response15(BaseModel):
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


class Response17(BaseModel):
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


class Response18(BaseModel):
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


class Response23(BaseModel):
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


class DataWarehouseNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    distinct_id_field: str
    dw_source_type: Optional[str] = None
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    table_name: str
    timestamp_field: str
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class DocumentSimilarityQueryResponse(BaseModel):
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


class EntityNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: NodeKind
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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
    id: str
    last_event: Optional[LastEvent] = None
    last_seen: datetime
    library: Optional[str] = None
    name: Optional[str] = None
    revenue: Optional[float] = None
    status: Status


class ErrorTrackingIssueFilteringToolOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    filterTestAccounts: Optional[bool] = None
    newFilters: Optional[
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
    orderBy: OrderBy1
    orderDirection: Optional[OrderDirection1] = None
    removedFilterIndexes: Optional[list[int]] = None
    searchQuery: Optional[str] = None
    status: Optional[Status2] = None


class ErrorTrackingQueryResponse(BaseModel):
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


class ErrorTrackingSimilarIssuesQueryResponse(BaseModel):
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


class EventTaxonomyQueryResponse(BaseModel):
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


class EventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    event: Optional[str] = Field(default=None, description="The event or `null` for all events.")
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsNode"] = "EventsNode"
    limit: Optional[int] = None
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class EventsQueryResponse(BaseModel):
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


class ExperimentDataWarehouseNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    data_warehouse_join_key: str
    events_join_key: str
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["ExperimentDataWarehouseNode"] = "ExperimentDataWarehouseNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    table_name: str
    timestamp_field: str
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class FunnelExclusionActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    funnelFromStep: int
    funnelToStep: int
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FunnelExclusionEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    event: Optional[str] = Field(default=None, description="The event or `null` for all events.")
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    funnelFromStep: int
    funnelToStep: int
    kind: Literal["EventsNode"] = "EventsNode"
    limit: Optional[int] = None
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FunnelsQueryResponse(BaseModel):
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


class GenericCachedQueryResponse(BaseModel):
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timezone: str


class GroupsQueryResponse(BaseModel):
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


class HeatMapQuerySource(RootModel[EventsNode]):
    root: EventsNode


class HogQLFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    filterTestAccounts: Optional[bool] = None
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


class LogsQueryResponse(BaseModel):
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


class MarketingAnalyticsAggregatedQueryResponse(BaseModel):
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


class MarketingAnalyticsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    attribution_mode: Optional[AttributionMode] = None
    attribution_window_days: Optional[float] = None
    campaign_name_mappings: Optional[dict[str, dict[str, list[str]]]] = None
    conversion_goals: Optional[list[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]]] = None
    sources_map: Optional[dict[str, SourceMap]] = None


class MarketingAnalyticsTableQueryResponse(BaseModel):
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


class PersonsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cohort: Optional[int] = None
    distinctId: Optional[str] = None
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    search: Optional[str] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class PlanningMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    steps: list[PlanningStep]
    type: Literal["ai/planning"] = "ai/planning"


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


class QueryResponseAlternative2(BaseModel):
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


class QueryResponseAlternative4(BaseModel):
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


class QueryResponseAlternative5(BaseModel):
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


class QueryResponseAlternative10(BaseModel):
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


class QueryResponseAlternative13(BaseModel):
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


class QueryResponseAlternative14(BaseModel):
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


class QueryResponseAlternative20(BaseModel):
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


class QueryResponseAlternative21(BaseModel):
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


class QueryResponseAlternative22(BaseModel):
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


class QueryResponseAlternative23(BaseModel):
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


class QueryResponseAlternative25(BaseModel):
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


class QueryResponseAlternative26(BaseModel):
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


class QueryResponseAlternative28(BaseModel):
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


class QueryResponseAlternative29(BaseModel):
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
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative31(BaseModel):
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
    results: Any
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative33(BaseModel):
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


class QueryResponseAlternative34(BaseModel):
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


class QueryResponseAlternative35(BaseModel):
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


class QueryResponseAlternative36(BaseModel):
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


class QueryResponseAlternative38(BaseModel):
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


class QueryResponseAlternative39(BaseModel):
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


class QueryResponseAlternative40(BaseModel):
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


class QueryResponseAlternative41(BaseModel):
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


class QueryResponseAlternative43(BaseModel):
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


class QueryResponseAlternative44(BaseModel):
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


class QueryResponseAlternative45(BaseModel):
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


class QueryResponseAlternative46(BaseModel):
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


class QueryResponseAlternative47(BaseModel):
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


class QueryResponseAlternative48(BaseModel):
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


class QueryResponseAlternative52(BaseModel):
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


class QueryResponseAlternative53(BaseModel):
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


class QueryResponseAlternative54(BaseModel):
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


class QueryResponseAlternative58(BaseModel):
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


class QueryResponseAlternative59(BaseModel):
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


class QueryResponseAlternative60(BaseModel):
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


class QueryResponseAlternative62(BaseModel):
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


class QueryResponseAlternative63(BaseModel):
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


class QueryResponseAlternative65(BaseModel):
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


class QueryResponseAlternative67(BaseModel):
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


class QueryResponseAlternative69(BaseModel):
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


class QueryResponseAlternative70(BaseModel):
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


class QueryResponseAlternative71(BaseModel):
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


class QueryResponseAlternative72(BaseModel):
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
    results: list[VectorSearchResponseItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative75(BaseModel):
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


class RecordingsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    has_next: bool
    results: list[SessionRecordingType]


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


class RetentionFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: Optional[bool] = None
    dashboardDisplay: Optional[RetentionDashboardDisplayType] = None
    display: Optional[ChartDisplayType] = Field(default=None, description="controls the display of the retention graph")
    meanRetentionCalculation: Optional[MeanRetentionCalculation] = None
    minimumOccurrences: Optional[int] = None
    period: Optional[RetentionPeriod] = RetentionPeriod.DAY
    retentionReference: Optional[RetentionReference] = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retentionType: Optional[RetentionType] = None
    returningEntity: Optional[RetentionEntity] = None
    showTrendLines: Optional[bool] = None
    targetEntity: Optional[RetentionEntity] = None
    timeWindowMode: Optional[TimeWindowMode] = Field(
        default=None, description="The time window mode to use for retention calculations"
    )
    totalIntervals: Optional[int] = 8


class RetentionFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: Optional[bool] = None
    mean_retention_calculation: Optional[MeanRetentionCalculation] = None
    period: Optional[RetentionPeriod] = None
    retention_reference: Optional[RetentionReference] = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retention_type: Optional[RetentionType] = None
    returning_entity: Optional[RetentionEntity] = None
    show_mean: Optional[bool] = None
    target_entity: Optional[RetentionEntity] = None
    total_intervals: Optional[int] = None


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


class RevenueAnalyticsBaseQueryRevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsGrossRevenueQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMRRQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMetricsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsOverviewQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: NodeKind
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsTopCustomersQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: Optional[list[RevenueAnalyticsEventItem]] = []
    filter_test_accounts: Optional[bool] = False
    goals: Optional[list[RevenueAnalyticsGoal]] = []


class RevenueAnalyticsGrossRevenueQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: Optional[DateRange] = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsGrossRevenueQuery"] = "RevenueAnalyticsGrossRevenueQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsGrossRevenueQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsMRRQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: Optional[DateRange] = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMRRQuery"] = "RevenueAnalyticsMRRQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMRRQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsMetricsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: Optional[DateRange] = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMetricsQuery"] = "RevenueAnalyticsMetricsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsMetricsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsOverviewQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: Literal["RevenueAnalyticsOverviewQuery"] = "RevenueAnalyticsOverviewQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsOverviewQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsTopCustomersQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    groupBy: RevenueAnalyticsTopCustomersGroupBy
    kind: Literal["RevenueAnalyticsTopCustomersQuery"] = "RevenueAnalyticsTopCustomersQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[RevenueAnalyticsPropertyFilter]
    response: Optional[RevenueAnalyticsTopCustomersQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueExampleDataWarehouseTablesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["RevenueExampleDataWarehouseTablesQuery"] = "RevenueExampleDataWarehouseTablesQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    response: Optional[RevenueExampleDataWarehouseTablesQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class RevenueExampleEventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["RevenueExampleEventsQuery"] = "RevenueExampleEventsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    response: Optional[RevenueExampleEventsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class SessionAttributionExplorerQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    filters: Optional[Filters] = None
    groupBy: list[SessionAttributionGroupBy]
    kind: Literal["SessionAttributionExplorerQuery"] = "SessionAttributionExplorerQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    response: Optional[SessionAttributionExplorerQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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
    personId: Optional[str] = Field(default=None, description="Fetch sessions only for a given person")
    response: Optional[SessionsTimelineQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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
    name: str
    questions: list[SurveyQuestionSchema]
    responses_limit: Optional[float] = None
    should_launch: Optional[bool] = None
    start_date: Optional[str] = None
    type: SurveyType


class TeamTaxonomyQueryResponse(BaseModel):
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


class TileFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_filter: Optional[BreakdownFilter] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
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


class TraceQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    kind: Literal["TraceQuery"] = "TraceQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[TraceQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    traceId: str
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TracesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    filterTestAccounts: Optional[bool] = None
    groupKey: Optional[str] = None
    groupTypeIndex: Optional[int] = None
    kind: Literal["TracesQuery"] = "TracesQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    personId: Optional[str] = Field(default=None, description="Person who performed the event")
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[TracesQueryResponse] = None
    showColumnConfigurator: Optional[bool] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class UsageMetricsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_key: Optional[str] = Field(
        default=None, description="Group key. Required with group_type_index for group queries."
    )
    group_type_index: Optional[int] = Field(
        default=None, description="Group type index. Required with group_key for group queries."
    )
    kind: Literal["UsageMetricsQuery"] = "UsageMetricsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    person_id: Optional[str] = Field(
        default=None, description="Person ID to fetch metrics for. Mutually exclusive with group parameters."
    )
    response: Optional[UsageMetricsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class VectorSearchQueryResponse(BaseModel):
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


class WebAnalyticsExternalSummaryQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    kind: Literal["WebAnalyticsExternalSummaryQuery"] = "WebAnalyticsExternalSummaryQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebAnalyticsExternalSummaryQueryResponse] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebExternalClicksTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebExternalClicksTableQuery"] = "WebExternalClicksTableQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebExternalClicksTableQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    stripQueryParams: Optional[bool] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebGoalsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebGoalsQuery"] = "WebGoalsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebGoalsQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebOverviewQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebOverviewQuery"] = "WebOverviewQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebOverviewQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebPageURLSearchQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebPageURLSearchQuery"] = "WebPageURLSearchQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebPageURLSearchQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    searchTerm: Optional[str] = None
    stripQueryParams: Optional[bool] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebStatsTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownBy: WebStatsBreakdown
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeBounceRate: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    includeScrollDepth: Optional[bool] = None
    kind: Literal["WebStatsTableQuery"] = "WebStatsTableQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebStatsTableQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebTrendsQueryResponse(BaseModel):
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
    results: list[WebTrendsItem]
    samplingRate: Optional[SamplingRate] = None
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")
    usedPreAggregatedTables: Optional[bool] = None


class WebVitalsItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    action: WebVitalsItemAction
    data: list[float]
    days: list[str]


class WebVitalsPathBreakdownQueryResponse(BaseModel):
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


class WebVitalsQueryResponse(BaseModel):
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
    results: list[WebVitalsItem]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: Optional[str] = None
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[
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
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ActorsPropertyTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    groupTypeIndex: Optional[int] = None
    kind: Literal["ActorsPropertyTaxonomyQuery"] = "ActorsPropertyTaxonomyQuery"
    maxPropertyValues: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[str]
    response: Optional[ActorsPropertyTaxonomyQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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
        ErrorTrackingQueryResponse,
        LogsQueryResponse,
    ]


class AssistantBasePropertyFilter(
    RootModel[
        Union[
            AssistantDateTimePropertyFilter,
            AssistantSetPropertyFilter,
            Union[
                AssistantStringOrBooleanValuePropertyFilter,
                AssistantNumericValuePropertyFilter,
                AssistantArrayPropertyFilter,
            ],
        ]
    ]
):
    root: Union[
        AssistantDateTimePropertyFilter,
        AssistantSetPropertyFilter,
        Union[
            AssistantStringOrBooleanValuePropertyFilter,
            AssistantNumericValuePropertyFilter,
            AssistantArrayPropertyFilter,
        ],
    ]


class CachedErrorTrackingQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
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
    results: list[ErrorTrackingIssue]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedHogQLQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
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
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")


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


class CachedRetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RetentionResult]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
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
    is_cached: bool
    last_refresh: datetime
    limit: Optional[int] = None
    metadata: Optional[HogQLMetadataResponse] = Field(default=None, description="Query metadata output")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    offset: Optional[int] = None
    query: Optional[str] = Field(default=None, description="Input query string")
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebTrendsItem]
    samplingRate: Optional[SamplingRate] = None
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: Optional[list] = Field(default=None, description="Types of returned columns")
    usedPreAggregatedTables: Optional[bool] = None


class CachedWebVitalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: Optional[str] = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: Optional[str] = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    next_allowed_client_refresh: datetime
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: Optional[ResolvedDateRangeResponse] = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsItem]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


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


class Response19(BaseModel):
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


class DocumentSimilarityQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    distance_func: DistanceFunc
    document_types: list[str]
    kind: Literal["DocumentSimilarityQuery"] = "DocumentSimilarityQuery"
    limit: Optional[int] = None
    model: str
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    order_by: OrderBy
    order_direction: OrderDirection
    origin: EmbeddedDocument
    products: list[str]
    renderings: list[str]
    response: Optional[DocumentSimilarityQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    threshold: Optional[float] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class ErrorTrackingIssueCorrelationQueryResponse(BaseModel):
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


class ErrorTrackingSimilarIssuesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    issueId: str
    kind: Literal["ErrorTrackingSimilarIssuesQuery"] = "ErrorTrackingSimilarIssuesQuery"
    limit: Optional[int] = None
    maxDistance: Optional[float] = None
    modelName: Optional[EmbeddingModelName] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    rendering: Optional[str] = None
    response: Optional[ErrorTrackingSimilarIssuesQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class EventTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: Optional[int] = None
    event: Optional[str] = None
    kind: Literal["EventTaxonomyQuery"] = "EventTaxonomyQuery"
    maxPropertyValues: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: Optional[list[str]] = None
    response: Optional[EventTaxonomyQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentExposureCriteria(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exposure_config: Optional[Union[ExperimentEventExposureConfig, ActionsNode]] = None
    filterTestAccounts: Optional[bool] = None
    multiple_variant_handling: Optional[MultipleVariantHandling] = None


class ExperimentFunnelMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_order_type: Optional[StepOrderValue] = None
    metric_type: Literal["funnel"] = "funnel"
    series: list[Union[EventsNode, ActionsNode]]


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


class ExperimentRatioMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    metric_type: Literal["ratio"] = "ratio"
    numerator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]


class FunnelsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    binCount: Optional[int] = None
    breakdownAttributionType: Optional[BreakdownAttributionType] = BreakdownAttributionType.FIRST_TOUCH
    breakdownAttributionValue: Optional[int] = None
    exclusions: Optional[list[Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]]] = []
    funnelAggregateByHogQL: Optional[str] = None
    funnelFromStep: Optional[int] = None
    funnelOrderType: Optional[StepOrderValue] = StepOrderValue.ORDERED
    funnelStepReference: Optional[FunnelStepReference] = FunnelStepReference.TOTAL
    funnelToStep: Optional[int] = Field(
        default=None, description="To select the range of steps for trends & time to convert funnels, 0-indexed"
    )
    funnelVizType: Optional[FunnelVizType] = FunnelVizType.STEPS
    funnelWindowInterval: Optional[int] = 14
    funnelWindowIntervalUnit: Optional[FunnelConversionWindowTimeUnit] = FunnelConversionWindowTimeUnit.DAY
    goalLines: Optional[list[GoalLine]] = Field(default=None, description="Goal Lines")
    hiddenLegendBreakdowns: Optional[list[str]] = None
    layout: Optional[FunnelLayout] = FunnelLayout.VERTICAL
    resultCustomizations: Optional[dict[str, ResultCustomizationByValue]] = Field(
        default=None, description="Customizations for the appearance of result datasets."
    )
    showValuesOnSeries: Optional[bool] = False
    useUdf: Optional[bool] = None


class GroupsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[list[str]] = None
    properties: Optional[list[Union[GroupPropertyFilter, HogQLPropertyFilter]]] = None
    response: Optional[GroupsQueryResponse] = None
    search: Optional[str] = None
    select: Optional[list[str]] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class HogQLASTQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    explain: Optional[bool] = None
    filters: Optional[HogQLFilters] = None
    kind: Literal["HogQLASTQuery"] = "HogQLASTQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = Field(default=None, description="Client provided name of the query")
    query: dict[str, Any]
    response: Optional[HogQLQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    values: Optional[dict[str, Any]] = Field(
        default=None, description="Constant values that can be referenced with the {placeholder} syntax in the query"
    )
    variables: Optional[dict[str, HogQLVariable]] = Field(
        default=None, description="Variables to be substituted into the query"
    )
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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
    name: Optional[str] = Field(default=None, description="Client provided name of the query")
    query: str
    response: Optional[HogQLQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    values: Optional[dict[str, Any]] = Field(
        default=None, description="Constant values that can be referenced with the {placeholder} syntax in the query"
    )
    variables: Optional[dict[str, HogQLVariable]] = Field(
        default=None, description="Variables to be substituted into the query"
    )
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


class InsightFilter(
    RootModel[
        Union[
            TrendsFilter,
            FunnelsFilter,
            RetentionFilter,
            PathsFilter,
            StickinessFilter,
            LifecycleFilter,
            CalendarHeatmapFilter,
        ]
    ]
):
    root: Union[
        TrendsFilter,
        FunnelsFilter,
        RetentionFilter,
        PathsFilter,
        StickinessFilter,
        LifecycleFilter,
        CalendarHeatmapFilter,
    ]


class MarketingAnalyticsAggregatedQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    draftConversionGoal: Optional[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]] = Field(
        default=None, description="Draft conversion goal that can be set in the UI without saving"
    )
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    integrationFilter: Optional[IntegrationFilter] = Field(default=None, description="Filter by integration IDs")
    kind: Literal["MarketingAnalyticsAggregatedQuery"] = "MarketingAnalyticsAggregatedQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[MarketingAnalyticsAggregatedQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    select: Optional[list[str]] = Field(
        default=None, description="Return a limited set of data. Will use default columns if empty."
    )
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class MarketingAnalyticsTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    draftConversionGoal: Optional[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]] = Field(
        default=None, description="Draft conversion goal that can be set in the UI without saving"
    )
    filterTestAccounts: Optional[bool] = Field(default=None, description="Filter test accounts")
    includeAllConversions: Optional[bool] = Field(
        default=None, description="Include conversion goal rows even when they don't match campaign costs table"
    )
    includeRevenue: Optional[bool] = None
    integrationFilter: Optional[IntegrationFilter] = Field(default=None, description="Filter by integration type")
    kind: Literal["MarketingAnalyticsTableQuery"] = "MarketingAnalyticsTableQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: Optional[list[list[Union[str, MarketingAnalyticsOrderByEnum]]]] = Field(
        default=None, description="Columns to order by - similar to EventsQuery format"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[MarketingAnalyticsTableQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    select: Optional[list[str]] = Field(
        default=None, description="Return a limited set of data. Will use default columns if empty."
    )
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class MaxInnerUniversalFiltersGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[
        Union[
            EventPropertyFilter,
            PersonPropertyFilter,
            SessionPropertyFilter,
            RecordingPropertyFilter,
            GroupPropertyFilter,
        ]
    ]


class MaxOuterUniversalFiltersGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[MaxInnerUniversalFiltersGroup]


class MaxRecordingUniversalFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    duration: list[RecordingDurationFilter]
    filter_group: MaxOuterUniversalFiltersGroup
    filter_test_accounts: Optional[bool] = None
    order: Optional[RecordingOrder] = RecordingOrder.START_TIME
    order_direction: Optional[RecordingOrderDirection] = Field(
        default=RecordingOrderDirection.DESC,
        description=(
            "Replay originally had all ordering as descending by specifying the field name, this runs counter to Django"
            " behavior where the field name specifies ascending sorting (e.g. the_field_name) and -the_field_name would"
            " indicate descending order to avoid invalidating or migrating all existing filters we keep DESC as the"
            " default or allow specification of an explicit order direction here"
        ),
    )


class PropertyGroupFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[PropertyGroupFilterValue]


class QueryResponseAlternative15(BaseModel):
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


class QueryResponseAlternative61(BaseModel):
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


class RecordingsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions: Optional[list[dict[str, Any]]] = None
    comment_text: Optional[RecordingPropertyFilter] = None
    console_log_filters: Optional[list[LogEntryPropertyFilter]] = None
    date_from: Optional[str] = "-3d"
    date_to: Optional[str] = None
    distinct_ids: Optional[list[str]] = None
    events: Optional[list[dict[str, Any]]] = None
    filter_test_accounts: Optional[bool] = None
    having_predicates: Optional[
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
    kind: Literal["RecordingsQuery"] = "RecordingsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    operand: Optional[FilterLogicalOperator] = FilterLogicalOperator.AND_
    order: Optional[RecordingOrder] = RecordingOrder.START_TIME
    order_direction: Optional[RecordingOrderDirection] = Field(
        default=RecordingOrderDirection.DESC,
        description=(
            "Replay originally had all ordering as descending by specifying the field name, this runs counter to Django"
            " behavior where the field name specifies ascending sorting (e.g. the_field_name) and -the_field_name would"
            " indicate descending order to avoid invalidating or migrating all existing filters we keep DESC as the"
            " default or allow specification of an explicit order direction here"
        ),
    )
    person_uuid: Optional[str] = None
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
    response: Optional[RecordingsQueryResponse] = None
    session_ids: Optional[list[str]] = None
    tags: Optional[QueryLogTags] = None
    user_modified_filters: Optional[dict[str, Any]] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class StickinessQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    intervalCount: Optional[int] = Field(
        default=None, description="How many intervals comprise a period. Only used for cohorts, otherwise default 1."
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
    response: Optional[StickinessQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    stickinessFilter: Optional[StickinessFilter] = Field(
        default=None, description="Properties specific to the stickiness insight"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TeamTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["TeamTaxonomyQuery"] = "TeamTaxonomyQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[TeamTaxonomyQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class TrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdownFilter: Optional[BreakdownFilter] = Field(default=None, description="Breakdown of the events and actions")
    compareFilter: Optional[CompareFilter] = Field(default=None, description="Compare to date range")
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = Field(
        default=None, description="Whether we should be comparing against a specific conversion goal"
    )
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
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
    response: Optional[TrendsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    trendsFilter: Optional[TrendsFilter] = Field(default=None, description="Properties specific to the trends insight")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class VectorSearchQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    embedding: list[float]
    embeddingVersion: Optional[float] = None
    kind: Literal["VectorSearchQuery"] = "VectorSearchQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[VectorSearchQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    interval: IntervalType
    kind: Literal["WebTrendsQuery"] = "WebTrendsQuery"
    limit: Optional[int] = None
    metrics: list[WebTrendsMetric]
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebTrendsQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class WebVitalsPathBreakdownQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebVitalsPathBreakdownQuery"] = "WebVitalsPathBreakdownQuery"
    metric: WebVitalsMetric
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    percentile: WebVitalsPercentile
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebVitalsPathBreakdownQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    tags: Optional[QueryLogTags] = None
    thresholds: list[float] = Field(..., max_length=2, min_length=2)
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class CachedErrorTrackingIssueCorrelationQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: Optional[list[str]] = None
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
    results: list[ErrorTrackingCorrelatedIssue]
    timezone: str
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedExperimentTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    count_query: Optional[TrendsQuery] = None
    credible_intervals: dict[str, list[float]]
    exposure_query: Optional[TrendsQuery] = None
    insight: list[dict[str, Any]]
    is_cached: bool
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    p_value: float
    probability: dict[str, float]
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    timezone: str
    variants: list[ExperimentVariantTrendsBaseStats]


class CalendarHeatmapQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    calendarHeatmapFilter: Optional[CalendarHeatmapFilter] = Field(
        default=None, description="Properties specific to the trends insight"
    )
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = Field(
        default=None, description="Whether we should be comparing against a specific conversion goal"
    )
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["CalendarHeatmapQuery"] = "CalendarHeatmapQuery"
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
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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
    results: list[ErrorTrackingCorrelatedIssue]
    timings: Optional[list[QueryTiming]] = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response22(BaseModel):
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


class DataVisualizationNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chartSettings: Optional[ChartSettings] = None
    display: Optional[ChartDisplayType] = None
    kind: Literal["DataVisualizationNode"] = "DataVisualizationNode"
    source: HogQLQuery
    tableSettings: Optional[TableSettings] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class ErrorTrackingIssueCorrelationQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[str]
    kind: Literal["ErrorTrackingIssueCorrelationQuery"] = "ErrorTrackingIssueCorrelationQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ErrorTrackingIssueCorrelationQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ErrorTrackingQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignee: Optional[ErrorTrackingIssueAssignee] = None
    dateRange: DateRange
    filterGroup: Optional[PropertyGroupFilter] = None
    filterTestAccounts: Optional[bool] = None
    groupKey: Optional[str] = None
    groupTypeIndex: Optional[int] = None
    issueId: Optional[str] = None
    kind: Literal["ErrorTrackingQuery"] = "ErrorTrackingQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: OrderBy1
    orderDirection: Optional[OrderDirection1] = None
    personId: Optional[str] = None
    response: Optional[ErrorTrackingQueryResponse] = None
    revenueEntity: Optional[RevenueEntity] = None
    revenuePeriod: Optional[RevenuePeriod] = None
    searchQuery: Optional[str] = None
    status: Optional[Status2] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    volumeResolution: int
    withAggregations: Optional[bool] = None
    withFirstEvent: Optional[bool] = None
    withLastEvent: Optional[bool] = None


class ExperimentExposureQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    end_date: Optional[str] = None
    experiment_id: Optional[int] = None
    experiment_name: str
    exposure_criteria: Optional[ExperimentExposureCriteria] = None
    feature_flag: dict[str, Any]
    holdout: Optional[ExperimentHoldoutType] = None
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ExperimentExposureQueryResponse] = None
    start_date: Optional[str] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentFunnelMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class ExperimentMeanMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ignore_zeros: Optional[bool] = None
    lower_bound_percentile: Optional[float] = None
    metric_type: Literal["mean"] = "mean"
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    upper_bound_percentile: Optional[float] = None


class ExperimentMetric(RootModel[Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]]):
    root: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]


class ExperimentMetricTypeProps(
    RootModel[Union[ExperimentMeanMetricTypeProps, ExperimentFunnelMetricTypeProps, ExperimentRatioMetricTypeProps]]
):
    root: Union[ExperimentMeanMetricTypeProps, ExperimentFunnelMetricTypeProps, ExperimentRatioMetricTypeProps]


class ExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: Optional[ExperimentStatsBaseValidated] = None
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


class ExperimentTrendsQueryResponse(BaseModel):
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


class FunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdownFilter: Optional[BreakdownFilter] = Field(default=None, description="Breakdown of the events and actions")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelsFilter: Optional[FunnelsFilter] = Field(
        default=None, description="Properties specific to the funnels insight"
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
    response: Optional[FunnelsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class InsightsQueryBaseFunnelsQueryResponse(BaseModel):
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
    response: Optional[FunnelsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseLifecycleQueryResponse(BaseModel):
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
    response: Optional[LifecycleQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBasePathsQueryResponse(BaseModel):
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
    response: Optional[PathsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseRetentionQueryResponse(BaseModel):
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
    response: Optional[RetentionQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseTrendsQueryResponse(BaseModel):
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
    response: Optional[TrendsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class LegacyExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]


class LifecycleQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: Optional[IntervalType] = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["LifecycleQuery"] = "LifecycleQuery"
    lifecycleFilter: Optional[LifecycleFilter] = Field(
        default=None, description="Properties specific to the lifecycle insight"
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
    response: Optional[LifecycleQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class LogsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    filterGroup: PropertyGroupFilter
    kind: Literal["LogsQuery"] = "LogsQuery"
    limit: Optional[int] = None
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = None
    orderBy: Optional[OrderBy3] = None
    response: Optional[LogsQueryResponse] = None
    searchTerm: Optional[str] = None
    serviceNames: list[str]
    severityLevels: list[LogSeverityLevel]
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class QueryResponseAlternative16(BaseModel):
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


class QueryResponseAlternative17(BaseModel):
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


class QueryResponseAlternative18(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: Optional[ExperimentStatsBaseValidated] = None
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


class QueryResponseAlternative56(BaseModel):
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


class QueryResponseAlternative57(BaseModel):
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


class RetentionQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    breakdownFilter: Optional[BreakdownFilter] = Field(default=None, description="Breakdown of the events and actions")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
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
    response: Optional[RetentionQueryResponse] = None
    retentionFilter: RetentionFilter = Field(..., description="Properties specific to the retention insight")
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class StickinessActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[Compare] = None
    day: Optional[Union[str, int]] = None
    includeRecordings: Optional[bool] = None
    kind: Literal["StickinessActorsQuery"] = "StickinessActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    operator: Optional[StickinessOperator] = None
    response: Optional[ActorsQueryResponse] = None
    series: Optional[int] = None
    source: StickinessQuery
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


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


class CachedExperimentFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: Optional[FunnelsQuery] = None
    insight: list[list[dict[str, Any]]]
    is_cached: bool
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    probability: dict[str, float]
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    timezone: str
    variants: list[ExperimentVariantFunnelsBaseStats]


class CachedExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: Optional[ExperimentStatsBaseValidated] = None
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: Optional[dict[str, list[float]]] = None
    insight: Optional[list[dict[str, Any]]] = None
    is_cached: bool
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    last_refresh: datetime
    metric: Optional[Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]] = None
    next_allowed_client_refresh: datetime
    p_value: Optional[float] = None
    probability: Optional[dict[str, float]] = None
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: Optional[ExperimentSignificanceCode] = None
    significant: Optional[bool] = None
    stats_version: Optional[int] = None
    timezone: str
    variant_results: Optional[
        Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]
    ] = None
    variants: Optional[Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]] = None


class CachedLegacyExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: Optional[datetime] = None
    calculation_trigger: Optional[str] = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: dict[str, list[float]]
    insight: list[dict[str, Any]]
    is_cached: bool
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    last_refresh: datetime
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    next_allowed_client_refresh: datetime
    p_value: float
    probability: dict[str, float]
    query_metadata: Optional[dict[str, Any]] = None
    query_status: Optional[QueryStatus] = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: Optional[int] = None
    timezone: str
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]


class Response21(BaseModel):
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


class ExperimentFunnelsQueryResponse(BaseModel):
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


class ExperimentQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experiment_id: Optional[int] = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = None
    response: Optional[ExperimentQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: TrendsQuery
    experiment_id: Optional[int] = None
    exposure_query: Optional[TrendsQuery] = None
    fingerprint: Optional[str] = None
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = None
    response: Optional[ExperimentTrendsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FunnelPathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelPathType: Optional[FunnelPathType] = None
    funnelSource: FunnelsQuery
    funnelStep: Optional[int] = None


class FunnelsActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelStep: Optional[int] = Field(
        default=None,
        description=(
            "Index of the step for which we want to get the timestamp for, per person. Positive for converted persons,"
            " negative for dropped of persons."
        ),
    )
    funnelStepBreakdown: Optional[Union[int, str, float, list[Union[int, str, float]]]] = Field(
        default=None,
        description=(
            "The breakdown value for which to get persons for. This is an array for person and event properties, a"
            " string for groups and an integer for cohorts."
        ),
    )
    funnelTrendsDropOff: Optional[bool] = None
    funnelTrendsEntrancePeriodStart: Optional[str] = Field(
        default=None,
        description="Used together with `funnelTrendsDropOff` for funnels time conversion date for the persons modal.",
    )
    includeRecordings: Optional[bool] = None
    kind: Literal["FunnelsActorsQuery"] = "FunnelsActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    source: FunnelsQuery
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class PathsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: Optional[int] = Field(default=None, description="Groups aggregation")
    dataColorTheme: Optional[float] = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: Optional[DateRange] = Field(default=None, description="Date range for the query")
    filterTestAccounts: Optional[bool] = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelPathsFilter: Optional[FunnelPathsFilter] = Field(
        default=None, description="Used for displaying paths in relation to funnel steps."
    )
    kind: Literal["PathsQuery"] = "PathsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    pathsFilter: PathsFilter = Field(..., description="Properties specific to the paths insight")
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
    response: Optional[PathsQueryResponse] = None
    samplingFactor: Optional[float] = Field(default=None, description="Sampling rate")
    tags: Optional[QueryLogTags] = Field(default=None, description="Tags that will be added to the Query log comment")
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class QueryResponseAlternative66(BaseModel):
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
            QueryResponseAlternative22,
            QueryResponseAlternative23,
            QueryResponseAlternative25,
            QueryResponseAlternative26,
            QueryResponseAlternative27,
            QueryResponseAlternative28,
            QueryResponseAlternative29,
            QueryResponseAlternative30,
            QueryResponseAlternative31,
            QueryResponseAlternative32,
            QueryResponseAlternative33,
            QueryResponseAlternative34,
            Any,
            QueryResponseAlternative35,
            QueryResponseAlternative36,
            QueryResponseAlternative37,
            QueryResponseAlternative38,
            QueryResponseAlternative39,
            QueryResponseAlternative40,
            QueryResponseAlternative41,
            QueryResponseAlternative43,
            QueryResponseAlternative44,
            QueryResponseAlternative45,
            QueryResponseAlternative46,
            QueryResponseAlternative47,
            QueryResponseAlternative48,
            QueryResponseAlternative49,
            QueryResponseAlternative50,
            QueryResponseAlternative52,
            QueryResponseAlternative53,
            QueryResponseAlternative54,
            QueryResponseAlternative56,
            QueryResponseAlternative57,
            QueryResponseAlternative58,
            QueryResponseAlternative59,
            QueryResponseAlternative60,
            QueryResponseAlternative61,
            QueryResponseAlternative62,
            QueryResponseAlternative63,
            QueryResponseAlternative65,
            QueryResponseAlternative66,
            QueryResponseAlternative67,
            QueryResponseAlternative68,
            QueryResponseAlternative69,
            QueryResponseAlternative70,
            QueryResponseAlternative71,
            QueryResponseAlternative72,
            QueryResponseAlternative74,
            QueryResponseAlternative75,
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
        QueryResponseAlternative25,
        QueryResponseAlternative26,
        QueryResponseAlternative27,
        QueryResponseAlternative28,
        QueryResponseAlternative29,
        QueryResponseAlternative30,
        QueryResponseAlternative31,
        QueryResponseAlternative32,
        QueryResponseAlternative33,
        QueryResponseAlternative34,
        Any,
        QueryResponseAlternative35,
        QueryResponseAlternative36,
        QueryResponseAlternative37,
        QueryResponseAlternative38,
        QueryResponseAlternative39,
        QueryResponseAlternative40,
        QueryResponseAlternative41,
        QueryResponseAlternative43,
        QueryResponseAlternative44,
        QueryResponseAlternative45,
        QueryResponseAlternative46,
        QueryResponseAlternative47,
        QueryResponseAlternative48,
        QueryResponseAlternative49,
        QueryResponseAlternative50,
        QueryResponseAlternative52,
        QueryResponseAlternative53,
        QueryResponseAlternative54,
        QueryResponseAlternative56,
        QueryResponseAlternative57,
        QueryResponseAlternative58,
        QueryResponseAlternative59,
        QueryResponseAlternative60,
        QueryResponseAlternative61,
        QueryResponseAlternative62,
        QueryResponseAlternative63,
        QueryResponseAlternative65,
        QueryResponseAlternative66,
        QueryResponseAlternative67,
        QueryResponseAlternative68,
        QueryResponseAlternative69,
        QueryResponseAlternative70,
        QueryResponseAlternative71,
        QueryResponseAlternative72,
        QueryResponseAlternative74,
        QueryResponseAlternative75,
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


class DatabaseSchemaQueryResponse(BaseModel):
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


class ExperimentFunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experiment_id: Optional[int] = None
    fingerprint: Optional[str] = None
    funnels_query: FunnelsQuery
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    name: Optional[str] = None
    response: Optional[ExperimentFunnelsQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    uuid: Optional[str] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class FunnelCorrelationQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelCorrelationEventExcludePropertyNames: Optional[list[str]] = None
    funnelCorrelationEventNames: Optional[list[str]] = None
    funnelCorrelationExcludeEventNames: Optional[list[str]] = None
    funnelCorrelationExcludeNames: Optional[list[str]] = None
    funnelCorrelationNames: Optional[list[str]] = None
    funnelCorrelationType: FunnelCorrelationResultsType
    kind: Literal["FunnelCorrelationQuery"] = "FunnelCorrelationQuery"
    response: Optional[FunnelCorrelationResponse] = None
    source: FunnelsActorsQuery
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightVizNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    embedded: Optional[bool] = Field(default=None, description="Query is embedded inside another bordered component")
    full: Optional[bool] = Field(
        default=None, description="Show with most visual options enabled. Used in insight scene."
    )
    hidePersonsModal: Optional[bool] = None
    hideTooltipOnScroll: Optional[bool] = None
    kind: Literal["InsightVizNode"] = "InsightVizNode"
    showCorrelationTable: Optional[bool] = None
    showFilters: Optional[bool] = None
    showHeader: Optional[bool] = None
    showLastComputation: Optional[bool] = None
    showLastComputationRefresh: Optional[bool] = None
    showResults: Optional[bool] = None
    showTable: Optional[bool] = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    suppressSessionAnalysisWarning: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    vizSpecificOptions: Optional[VizSpecificOptions] = None


class MultiVisualizationMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    commentary: Optional[str] = None
    id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    type: Literal["ai/multi_viz"] = "ai/multi_viz"
    visualizations: list[VisualizationItem]


class WebVitalsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    conversionGoal: Optional[Union[ActionConversionGoal, CustomEventConversionGoal]] = None
    dateRange: Optional[DateRange] = None
    doPathCleaning: Optional[bool] = None
    filterTestAccounts: Optional[bool] = None
    includeRevenue: Optional[bool] = None
    kind: Literal["WebVitalsQuery"] = "WebVitalsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    orderBy: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: Optional[WebGoalsQueryResponse] = None
    sampling: Optional[WebAnalyticsSampling] = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    tags: Optional[QueryLogTags] = None
    useSessionsTable: Optional[bool] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class DatabaseSchemaQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["DatabaseSchemaQuery"] = "DatabaseSchemaQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[DatabaseSchemaQueryResponse] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class EndpointRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_age_seconds: Optional[float] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None
    query: Optional[
        Union[HogQLQuery, Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery]]
    ] = None


class FunnelCorrelationActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelCorrelationPersonConverted: Optional[bool] = None
    funnelCorrelationPersonEntity: Optional[Union[EventsNode, ActionsNode, DataWarehouseNode]] = None
    funnelCorrelationPropertyValues: Optional[
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
    includeRecordings: Optional[bool] = None
    kind: Literal["FunnelCorrelationActorsQuery"] = "FunnelCorrelationActorsQuery"
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    response: Optional[ActorsQueryResponse] = None
    source: FunnelCorrelationQuery
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[Union[str, list[str], int]] = None
    compare: Optional[Compare] = None
    day: Optional[Union[str, int]] = None
    includeRecordings: Optional[bool] = None
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
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class InsightActorsQueryOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["InsightActorsQueryOptions"] = "InsightActorsQueryOptions"
    response: Optional[InsightActorsQueryOptionsResponse] = None
    source: Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery]
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class SessionBatchEventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: Optional[int] = Field(default=None, description="Show events matching a given action")
    after: Optional[str] = Field(default=None, description="Only fetch events that happened after this timestamp")
    before: Optional[str] = Field(default=None, description="Only fetch events that happened before this timestamp")
    event: Optional[str] = Field(default=None, description="Limit to events matching this string")
    filterTestAccounts: Optional[bool] = Field(default=None, description="Filter test accounts")
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    group_by_session: Optional[bool] = Field(
        default=None, description="Whether to group results by session_id in the response"
    )
    kind: Literal["SessionBatchEventsQuery"] = "SessionBatchEventsQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
    personId: Optional[str] = Field(default=None, description="Show events for a given person")
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[SessionBatchEventsQueryResponse] = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    session_ids: list[str] = Field(
        ..., description="List of session IDs to fetch events for. Will be translated to $session_id IN filter."
    )
    source: Optional[InsightActorsQuery] = Field(default=None, description="source for querying events for insights")
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    where: Optional[list[str]] = Field(default=None, description="HogQL filters to apply on returned data")


class ActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fixedProperties: Optional[
        list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]]
    ] = Field(
        default=None,
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
    orderBy: Optional[list[str]] = None
    properties: Optional[
        Union[
            list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]],
            PropertyGroupFilterValue,
        ]
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
    source: Optional[
        Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery, HogQLQuery]
    ] = None
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class EventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: Optional[int] = Field(default=None, description="Show events matching a given action")
    after: Optional[str] = Field(default=None, description="Only fetch events that happened after this timestamp")
    before: Optional[str] = Field(default=None, description="Only fetch events that happened before this timestamp")
    event: Optional[str] = Field(default=None, description="Limit to events matching this string")
    filterTestAccounts: Optional[bool] = Field(default=None, description="Filter test accounts")
    fixedProperties: Optional[
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
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsQuery"] = "EventsQuery"
    limit: Optional[int] = Field(default=None, description="Number of rows to return")
    modifiers: Optional[HogQLQueryModifiers] = Field(
        default=None, description="Modifiers used when performing the query"
    )
    offset: Optional[int] = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
    personId: Optional[str] = Field(default=None, description="Show events for a given person")
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
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[EventsQueryResponse] = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    source: Optional[InsightActorsQuery] = Field(default=None, description="source for querying events for insights")
    tags: Optional[QueryLogTags] = None
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")
    where: Optional[list[str]] = Field(default=None, description="HogQL filters to apply on returned data")


class HasPropertiesNode(RootModel[Union[EventsNode, EventsQuery, PersonsNode]]):
    root: Union[EventsNode, EventsQuery, PersonsNode]


class DataTableNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    allowSorting: Optional[bool] = Field(
        default=None, description="Can the user click on column headers to sort the table? (default: true)"
    )
    columns: Optional[list[str]] = Field(
        default=None, description="Columns shown in the table, unless the `source` provides them."
    )
    context: Optional[DataTableNodeViewPropsContext] = Field(
        default=None, description="Context for the table, used by components like ColumnConfigurator"
    )
    defaultColumns: Optional[list[str]] = Field(
        default=None, description="Default columns to use when resetting column configuration"
    )
    embedded: Optional[bool] = Field(default=None, description="Uses the embedded version of LemonTable")
    expandable: Optional[bool] = Field(
        default=None, description="Can expand row to show raw event data (default: true)"
    )
    full: Optional[bool] = Field(default=None, description="Show with most visual options enabled. Used in scenes.")
    hiddenColumns: Optional[list[str]] = Field(
        default=None, description="Columns that aren't shown in the table, even if in columns or returned data"
    )
    kind: Literal["DataTableNode"] = "DataTableNode"
    pinnedColumns: Optional[list[str]] = Field(
        default=None, description="Columns that are sticky when scrolling horizontally"
    )
    propertiesViaUrl: Optional[bool] = Field(default=None, description="Link properties via the URL (default: false)")
    response: Optional[
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
            Response23,
        ]
    ] = None
    showActions: Optional[bool] = Field(default=None, description="Show the kebab menu at the end of the row")
    showColumnConfigurator: Optional[bool] = Field(
        default=None, description="Show a button to configure the table's columns if possible"
    )
    showDateRange: Optional[bool] = Field(default=None, description="Show date range selector")
    showElapsedTime: Optional[bool] = Field(default=None, description="Show the time it takes to run a query")
    showEventFilter: Optional[bool] = Field(
        default=None, description="Include an event filter above the table (EventsNode only)"
    )
    showExport: Optional[bool] = Field(default=None, description="Show the export button")
    showHogQLEditor: Optional[bool] = Field(default=None, description="Include a HogQL query editor above HogQL tables")
    showOpenEditorButton: Optional[bool] = Field(
        default=None, description="Show a button to open the current query as a new insight. (default: true)"
    )
    showPersistentColumnConfigurator: Optional[bool] = Field(
        default=None, description="Show a button to configure and persist the table's default columns if possible"
    )
    showPropertyFilter: Optional[Union[bool, list[TaxonomicFilterGroupType]]] = Field(
        default=None, description="Include a property filter above the table"
    )
    showReload: Optional[bool] = Field(default=None, description="Show a reload button")
    showResultsTable: Optional[bool] = Field(default=None, description="Show a results table")
    showSavedFilters: Optional[bool] = Field(
        default=None, description="Show saved filters feature for this table (requires uniqueKey)"
    )
    showSavedQueries: Optional[bool] = Field(default=None, description="Shows a list of saved queries")
    showSearch: Optional[bool] = Field(default=None, description="Include a free text search field (PersonsNode only)")
    showTestAccountFilters: Optional[bool] = Field(default=None, description="Show filter to exclude test accounts")
    showTimings: Optional[bool] = Field(default=None, description="Show a detailed query timing breakdown")
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
        MarketingAnalyticsAggregatedQuery,
        ErrorTrackingQuery,
        ErrorTrackingIssueCorrelationQuery,
        ExperimentFunnelsQuery,
        ExperimentTrendsQuery,
        TracesQuery,
        TraceQuery,
    ] = Field(..., description="Source of the events")
    tags: Optional[QueryLogTags] = None
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


class QuerySchemaRoot(
    RootModel[
        Union[
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
            ErrorTrackingSimilarIssuesQuery,
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
        ]
    ]
):
    root: Union[
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
        ErrorTrackingSimilarIssuesQuery,
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


class RootAssistantMessage(
    RootModel[
        Union[
            VisualizationMessage,
            MultiVisualizationMessage,
            ReasoningMessage,
            AssistantMessage,
            HumanMessage,
            FailureMessage,
            NotebookUpdateMessage,
            PlanningMessage,
            TaskExecutionMessage,
            AssistantToolCallMessage,
        ]
    ]
):
    root: Union[
        VisualizationMessage,
        MultiVisualizationMessage,
        ReasoningMessage,
        AssistantMessage,
        HumanMessage,
        FailureMessage,
        NotebookUpdateMessage,
        PlanningMessage,
        TaskExecutionMessage,
        AssistantToolCallMessage,
    ]


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


ProsemirrorJSONContent.model_rebuild()
PropertyGroupFilterValue.model_rebuild()
HumanMessage.model_rebuild()
MaxDashboardContext.model_rebuild()
MaxInsightContext.model_rebuild()
QueryRequest.model_rebuild()
SourceConfig.model_rebuild()
