# mypy: disable-error-code="assignment"

from __future__ import annotations

from datetime import datetime
from enum import Enum, StrEnum
from typing import Any, Literal, Union

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
    date_to: str | None = Field(default=None, description="ISO8601 date string.")


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
    EDIT_CURRENT_INSIGHT = "edit_current_insight"
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
    id: str | None = None
    parent_tool_call_id: str | None = None
    tool_call_id: str
    type: Literal["tool"] = "tool"
    ui_payload: dict[str, Any] | None = Field(
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
    aggregationAxisFormat: AggregationAxisFormat | None = Field(
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
    aggregationAxisPostfix: str | None = Field(
        default=None,
        description=(
            "Custom postfix to add to the aggregation axis, e.g., ` clicks` to format 5 as `5 clicks`. You may need to"
            " add a space before postfix."
        ),
    )
    aggregationAxisPrefix: str | None = Field(
        default=None,
        description=(
            "Custom prefix to add to the aggregation axis, e.g., `$` for USD dollars. You may need to add a space after"
            " prefix."
        ),
    )
    decimalPlaces: float | None = Field(
        default=None,
        description=(
            "Number of decimal places to show. Do not add this unless you are sure that values will have a decimal"
            " point."
        ),
    )
    display: Display | None = Field(
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
    formulas: list[str] | None = Field(
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
    showLegend: bool | None = Field(
        default=False, description="Whether to show the legend describing series and breakdowns."
    )
    showPercentStackView: bool | None = Field(
        default=False, description="Whether to show a percentage of each series. Use only with"
    )
    showValuesOnSeries: bool | None = Field(default=False, description="Whether to show a value on each data point.")
    yAxisScaleType: YAxisScaleType | None = Field(
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
    id: str | None = None
    parent_tool_call_id: str | None = None


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


class ChartSettingsDisplay(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    color: str | None = None
    displayType: DisplayType | None = None
    label: str | None = None
    trendLine: bool | None = None
    yAxisPosition: YAxisPosition | None = None


class Style(StrEnum):
    NONE = "none"
    NUMBER = "number"
    PERCENT = "percent"


class ChartSettingsFormatting(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    decimalPlaces: float | None = None
    prefix: str | None = None
    style: Style | None = None
    suffix: str | None = None


class CompareFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: bool | None = Field(
        default=False, description="Whether to compare the current date range to a previous date range."
    )
    compare_to: str | None = Field(
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
    colorMode: ColorMode | None = None
    columnName: str
    id: str
    input: str
    templateId: str


class ContextMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: str | None = None
    parent_tool_call_id: str | None = None
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
    experiments_optimized: bool | None = None
    experiments_timestamp_key: str | None = None


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
    last_synced_at: str | None = None
    name: str
    should_sync: bool
    status: str | None = None
    latest_error: str | None = None


class DatabaseSchemaSource(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    last_synced_at: str | None = None
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
    date_from: str | None = None
    date_to: str | None = None
    explicitDate: bool | None = Field(
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
    attr_class: list[str] | None = None
    attr_id: str | None = None
    attributes: dict[str, str]
    href: str | None = None
    nth_child: float | None = None
    nth_of_type: float | None = None
    order: float | None = None
    tag_name: str
    text: str | None = None


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
    volumeRange: list[float] | None = None
    volume_buckets: list[VolumeBucket]


class ErrorTrackingIssueAssigneeType(StrEnum):
    USER = "user"
    ROLE = "role"


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
    is_identified: bool | None = None
    properties: dict[str, Any]


class EventType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distinct_id: str
    elements: list[ElementType]
    elements_chain: str | None = None
    event: str
    id: str
    person: Person | None = None
    person_id: str | None = None
    person_mode: str | None = None
    properties: dict[str, Any]
    timestamp: str
    uuid: str | None = None


class Properties(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    email: str | None = None
    name: str | None = None


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
    content: str | None = None
    id: str | None = None
    parent_tool_call_id: str | None = None
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
    field_loading: bool | None = Field(
        default=None, alias="_loading", description="Used to indicate pending actions, frontend only"
    )
    created_at: str | None = Field(default=None, description="Timestamp when file was added. Used to check persistence")
    href: str | None = Field(default=None, description="Object's URL")
    id: str = Field(..., description="Unique UUID for tree entry")
    last_viewed_at: str | None = Field(default=None, description="Timestamp when the file system entry was last viewed")
    meta: dict[str, Any] | None = Field(default=None, description="Metadata")
    path: str = Field(..., description="Object's name and folder")
    ref: str | None = Field(default=None, description="Object's ID or other unique reference")
    shortcut: bool | None = Field(default=None, description="Whether this is a shortcut or the actual item")
    tags: list[Tag] | None = Field(default=None, description="Tag for the product 'beta' / 'alpha'")
    type: str | None = Field(default=None, description="Type of object, used for icon, e.g. feature_flag, insight, etc")
    visualOrder: float | None = Field(default=None, description="Order of object in tree")


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
    field_loading: bool | None = Field(
        default=None, alias="_loading", description="Used to indicate pending actions, frontend only"
    )
    category: str | None = Field(default=None, description="Category label to place this under")
    created_at: str | None = Field(default=None, description="Timestamp when file was added. Used to check persistence")
    flag: str | None = None
    href: str | None = Field(default=None, description="Object's URL")
    iconColor: list[str] | None = Field(default=None, description="Color of the icon")
    iconType: FileSystemIconType | None = None
    id: str | None = None
    last_viewed_at: str | None = Field(default=None, description="Timestamp when the file system entry was last viewed")
    meta: dict[str, Any] | None = Field(default=None, description="Metadata")
    path: str = Field(..., description="Object's name and folder")
    protocol: str | None = Field(default=None, description='Protocol of the item, defaults to "project://"')
    ref: str | None = Field(default=None, description="Object's ID or other unique reference")
    sceneKey: str | None = Field(default=None, description="Match this with the a base scene key or a specific one")
    sceneKeys: list[str] | None = Field(default=None, description="List of all scenes exported by the app")
    shortcut: bool | None = Field(default=None, description="Whether this is a shortcut or the actual item")
    tags: list[Tag] | None = Field(default=None, description="Tag for the product 'beta' / 'alpha'")
    type: str | None = Field(default=None, description="Type of object, used for icon, e.g. feature_flag, insight, etc")
    visualOrder: float | None = Field(default=None, description="Order of object in tree")


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
    label: str | None = None
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
    custom_name: str | None = None
    funnel_from_step: float
    funnel_to_step: float
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


class FunnelStepsBreakdownResults(RootModel[list[list[dict[str, Any]]]]):
    root: list[list[dict[str, Any]]]


class FunnelStepsResults(RootModel[list[dict[str, Any]]]):
    root: list[dict[str, Any]]


class FunnelTimeToConvertResults(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    average_conversion_time: float | None = None
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
    borderColor: str | None = None
    displayIfCrossed: bool | None = None
    displayLabel: bool | None = None
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
    isNull: bool | None = None
    value: Any | None = None
    variableId: str


class HogQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytecode: list | None = None
    coloredBytecode: list | None = None
    results: Any
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


class InsightsThresholdBounds(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lower: float | None = None
    upper: float | None = None


class IntegrationFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    integrationSourceIds: list[str] | None = Field(
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
    uuid: str


class MaxActionContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    id: float
    name: str
    type: Literal["action"] = "action"


class MaxAddonInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    current_usage: float
    description: str
    docs_url: str | None = None
    has_exceeded_limit: bool
    is_used: bool
    name: str
    percentage_usage: float | None = None
    projected_amount_usd: str | None = None
    projected_amount_usd_with_limit: str | None = None
    type: str
    usage_limit: float | None = None


class SpendHistoryItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_type: BillingSpendResponseBreakdownType | None = None
    breakdown_value: Union[str, list[str]] | None = None
    data: list[float]
    dates: list[str]
    id: float
    label: str


class UsageHistoryItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_type: BillingUsageResponseBreakdownType | None = None
    breakdown_value: Union[str, list[str]] | None = None
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
    expires_at: str | None = None
    is_active: bool
    target: str | None = None


class MaxEventContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    id: str
    name: str | None = None
    type: Literal["event"] = "event"


class MaxProductInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    addons: list[MaxAddonInfo]
    current_usage: float | None = None
    custom_limit_usd: float | None = None
    description: str
    docs_url: str | None = None
    has_exceeded_limit: bool
    is_used: bool
    name: str
    next_period_custom_limit_usd: float | None = None
    percentage_usage: float
    projected_amount_usd: str | None = None
    projected_amount_usd_with_limit: str | None = None
    type: str
    usage_limit: float | None = None


class MinimalHedgehogConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    accessories: list[str]
    color: HedgehogColorOptions | None = None
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
    alias: str | None = None
    order: float | None = None
    regex: str | None = None


class PathType(StrEnum):
    FIELD_PAGEVIEW = "$pageview"
    FIELD_SCREEN = "$screen"
    CUSTOM_EVENT = "custom_event"
    HOGQL = "hogql"


class PathsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    created_at: str | None = None
    distinct_ids: list[str]
    id: str | None = None
    is_identified: bool | None = None
    name: str | None = None
    properties: dict[str, Any]
    uuid: str | None = None


class PlanningStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PlaywrightWorkspaceSetupData(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    organization_name: str | None = None


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
    attrs: dict[str, Any] | None = None
    type: str


class ProsemirrorJSONContent(BaseModel):
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


class QueryLogTags(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    productKey: str | None = Field(
        default=None,
        description=(
            "Product responsible for this query. Use string, there's no need to churn the Schema when we add a new"
            " product *"
        ),
    )
    scene: str | None = Field(
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
    bytecode: list | None = None
    coloredBytecode: list | None = None
    results: Any
    stdout: str | None = None


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
    id: str | None = None
    parent_tool_call_id: str | None = None
    substeps: list[str] | None = None
    type: Literal["ai/reasoning"] = "ai/reasoning"


class RecordingDurationFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: DurationType
    label: str | None = None
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
    label: str | None = None
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


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
    color: DataColorToken | None = None
    hidden: bool | None = None


class ResultCustomizationBy(StrEnum):
    VALUE = "value"
    POSITION = "position"


class ResultCustomizationByPosition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignmentBy: Literal["position"] = "position"
    color: DataColorToken | None = None
    hidden: bool | None = None


class ResultCustomizationByValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    mrr_or_gross: MrrOrGross | None = MrrOrGross.GROSS
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
    label: str | None = None
    operator: PropertyOperator
    type: Literal["revenue_analytics"] = "revenue_analytics"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class RevenueAnalyticsTopCustomersGroupBy(StrEnum):
    MONTH = "month"
    ALL = "all"


class RevenueCurrencyPropertyConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str | None = None
    static: CurrencyCode | None = None


class SamplingRate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator: float | None = None
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
    label: str | None = None
    operator: PropertyOperator
    type: Literal["session"] = "session"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


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
    detailed: bool | None = None
    hideExtraDetails: bool | None = None
    legend: bool | None = None
    noHeader: bool | None = None
    showInspector: bool | None = None
    whitelabel: bool | None = None


class SimilarIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str
    first_seen: str
    id: str
    library: str | None = None
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


class StickinessFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class SuggestedQuestionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    questions: list[str]


class SurveyAnalysisResponseItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    isOpenEnded: bool | None = Field(default=True, description="Whether this is an open-ended response")
    responseText: str | None = Field(default="", description="The response text content")
    timestamp: str | None = Field(default="", description="Response timestamp")


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
    index: float | None = None
    responseValues: dict[str, Union[str, float]] | None = None
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
    MAX_AI_CONTEXT = "max_ai_context"


class TestSetupRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: dict[str, Any] | None = None


class TestSetupResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    available_tests: list[str] | None = None
    error: str | None = None
    result: Any | None = None
    success: bool
    test_name: str


class TimelineEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[EventType]
    recording_duration_s: float | None = Field(default=None, description="Duration of the recording in seconds.")
    sessionId: str | None = Field(default=None, description="Session ID. None means out-of-session events")


class DetailedResultsAggregationType(StrEnum):
    TOTAL = "total"
    AVERAGE = "average"
    MEDIAN = "median"


class TrendsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class TrendsFormulaNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = Field(default=None, description="Optional user-defined name for the formula")
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
    hedgehog_config: MinimalHedgehogConfig | None = None
    id: float
    is_email_verified: Any | None = None
    last_name: str | None = None
    role_at_organization: str | None = None
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
    disableHoverOffset: bool | None = None
    hideAggregation: bool | None = None


class RETENTION(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hideLineGraph: bool | None = None
    hideSizeColumn: bool | None = None
    useSmallLayout: bool | None = None


class VizSpecificOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ActionsPie_1: ActionsPie | None = Field(default=None, alias="ActionsPie")
    RETENTION_1: RETENTION | None = Field(default=None, alias="RETENTION")


class WebAnalyticsExternalSummaryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class WebAnalyticsSampling(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    enabled: bool | None = None
    forceSamplingRate: SamplingRate | None = None


class WebOverviewItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: float | None = None
    isIncreaseBad: bool | None = None
    key: str
    kind: WebAnalyticsItemKind
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


class Metrics(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    Bounces: float | None = None
    PageViews: float | None = None
    SessionDuration: float | None = None
    Sessions: float | None = None
    TotalSessions: float | None = None
    UniqueUsers: float | None = None


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
    scale: Scale | None = None
    showGridLines: bool | None = None
    showTicks: bool | None = None
    startAtZero: bool | None = Field(default=None, description="Whether the Y axis should start at zero")


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
    breakdown_limit: int | None = Field(default=25, description="How many distinct values to show.")


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
    breakdown_group_type_index: int | None = Field(
        default=None,
        description=(
            "If `breakdown_type` is `group`, this is the index of the group. Use the index from the group mapping."
        ),
    )
    breakdown_limit: int | None = Field(default=25, description="How many distinct values to show.")
    breakdown_type: AssistantFunnelsBreakdownType | None = Field(
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
    binCount: int | None = Field(
        default=None,
        description=(
            "Use this setting only when `funnelVizType` is `time_to_convert`: number of bins to show in histogram."
        ),
    )
    exclusions: list[AssistantFunnelsExclusionEventsNode] | None = Field(
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
    funnelAggregateByHogQL: FunnelAggregateByHogQL | None = Field(
        default=None,
        description="Use this field only if the user explicitly asks to aggregate the funnel by unique sessions.",
    )
    funnelOrderType: StepOrderValue | None = Field(
        default=StepOrderValue.ORDERED,
        description=(
            "Defines the behavior of event matching between steps. Prefer the `strict` option unless explicitly told to"
            " use a different one. `ordered` - defines a sequential funnel. Step B must happen after Step A, but any"
            " number of events can happen between A and B. `strict` - defines a funnel where all events must happen in"
            " order. Step B must happen directly after Step A without any events in between. `any` - order doesn't"
            " matter. Steps can be completed in any sequence."
        ),
    )
    funnelStepReference: FunnelStepReference | None = Field(
        default=FunnelStepReference.TOTAL,
        description=(
            "Whether conversion shown in the graph should be across all steps or just relative to the previous step."
        ),
    )
    funnelVizType: FunnelVizType | None = Field(
        default=FunnelVizType.STEPS,
        description=(
            "Defines the type of visualization to use. The `steps` option is recommended. `steps` - shows a"
            " step-by-step funnel. Perfect to show a conversion rate of a sequence of events (default)."
            " `time_to_convert` - shows a histogram of the time it took to complete the funnel. `trends` - shows trends"
            " of the conversion rate of the whole sequence over time."
        ),
    )
    funnelWindowInterval: int | None = Field(
        default=14,
        description=(
            "Controls a time frame value for a conversion to be considered. Select a reasonable value based on the"
            " user's query. If needed, this can be practically unlimited by setting a large value, though it's rare to"
            " need that. Use in combination with `funnelWindowIntervalUnit`. The default value is 14 days."
        ),
    )
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | None = Field(
        default=FunnelConversionWindowTimeUnit.DAY,
        description=(
            "Controls a time frame interval for a conversion to be considered. Select a reasonable value based on the"
            " user's query. Use in combination with `funnelWindowInterval`. The default value is 14 days."
        ),
    )
    layout: FunnelLayout | None = Field(
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
    group_type_index: int | None = Field(default=None, description="Index of the group type from the group mapping.")
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
    form: AssistantForm | None = None
    thinking: list[dict[str, Any]] | None = None


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
    ) = Field(default=None, description="Property filters for the action.")
    type: Literal["actions"] = "actions"


class AssistantRetentionEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = Field(
        default=None, description="Custom name for the event if it is needed to be renamed."
    )
    name: str = Field(..., description="Event name from the plan.")
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
    ) = Field(default=None, description="Property filters for the event.")
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
    breakdown_limit: int | None = Field(default=25, description="How many distinct values to show.")
    breakdowns: list[Union[AssistantGroupMultipleBreakdownFilter, AssistantGenericMultipleBreakdownFilter]] = Field(
        ..., description="Use this field to define breakdowns.", max_length=3
    )


class AutocompleteCompletionItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    detail: str | None = Field(
        default=None,
        description=(
            "A human-readable string with additional information about this item, like type or symbol information."
        ),
    )
    documentation: str | None = Field(
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
    group_type_index: int | None = None
    histogram_bin_count: int | None = None
    normalize_url: bool | None = None
    property: Union[str, int]
    type: MultipleBreakdownType | None = None


class BreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Union[str, list[Union[str, int]], int] | None = None
    breakdown_group_type_index: int | None = None
    breakdown_hide_other_aggregation: bool | None = None
    breakdown_histogram_bin_count: int | None = None
    breakdown_limit: int | None = None
    breakdown_normalize_url: bool | None = None
    breakdown_type: BreakdownType | None = BreakdownType.EVENT
    breakdowns: list[Breakdown] | None = Field(default=None, max_length=3)


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
    display: ChartSettingsDisplay | None = None
    formatting: ChartSettingsFormatting | None = None


class ChartAxis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    column: str
    settings: Settings | None = None


class ChartSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    goalLines: list[GoalLine] | None = None
    leftYAxisSettings: YAxisSettings | None = None
    rightYAxisSettings: YAxisSettings | None = None
    seriesBreakdownColumn: str | None = None
    showLegend: bool | None = None
    showTotalRow: bool | None = None
    showXAxisBorder: bool | None = None
    showXAxisTicks: bool | None = None
    showYAxisBorder: bool | None = None
    stackBars100: bool | None = Field(default=None, description="Whether we fill the bars to 100% in stacked mode")
    xAxis: ChartAxis | None = None
    yAxis: list[ChartAxis] | None = None
    yAxisAtZero: bool | None = Field(
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
    cohort_name: str | None = None
    key: Literal["id"] = "id"
    label: str | None = None
    operator: PropertyOperator | None = PropertyOperator.IN_
    type: Literal["cohort"] = "cohort"
    value: int


class CustomChannelCondition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str
    key: CustomChannelField
    op: CustomChannelOperator
    value: Union[str, list[str]] | None = None


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
    eventDefinitionId: str | None = None
    type: DataTableNodeViewPropsContextType


class DataWarehousePersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: str | None = None
    operator: PropertyOperator
    type: Literal["data_warehouse_person_property"] = "data_warehouse_person_property"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class DataWarehousePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: str | None = None
    operator: PropertyOperator
    type: Literal["data_warehouse"] = "data_warehouse"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class DataWarehouseViewLink(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    configuration: DataWarehouseViewLinkConfiguration | None = None
    created_at: str | None = None
    created_by: UserBasicType | None = None
    field_name: str | None = None
    id: str
    joining_table_key: str | None = None
    joining_table_name: str | None = None
    source_table_key: str | None = None
    source_table_name: str | None = None


class DatabaseSchemaField(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chain: list[Union[str, int]] | None = None
    fields: list[str] | None = None
    hogql_value: str
    id: str | None = None
    name: str
    schema_valid: bool
    table: str | None = None
    type: DatabaseSerializedFieldType


class DatabaseSchemaPostHogTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    row_count: float | None = None
    type: Literal["posthog"] = "posthog"


class DatabaseSchemaSystemTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    row_count: float | None = None
    type: Literal["system"] = "system"


class DatabaseSchemaTableCommon(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    row_count: float | None = None
    type: DatabaseSchemaTableType


class Day(RootModel[int]):
    root: int


class DeepResearchNotebook(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    category: Literal["deep_research"] = "deep_research"
    notebook_id: str
    notebook_type: DeepResearchType | None = None
    title: str


class ElementPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Key
    label: str | None = None
    operator: PropertyOperator
    type: Literal["element"] = "element"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class EmbeddingDistance(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    distance: float
    origin: EmbeddingRecord | None = None
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
    label: str | None = None
    operator: PropertyOperator
    type: Literal["error_tracking_issue"] = "error_tracking_issue"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class EventMetadataPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: str | None = None
    operator: PropertyOperator
    type: Literal["event_metadata"] = "event_metadata"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


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
    label: str | None = None
    operator: PropertyOperator | None = PropertyOperator.EXACT
    type: Literal["event"] = Field(default="event", description="Event properties")
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


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
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    fingerprint: str | None = None
    goal: ExperimentMetricGoal | None = None
    isSharedMetric: bool | None = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    name: str | None = None
    response: dict[str, Any] | None = None
    sharedMetricId: float | None = None
    uuid: str | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentStatsBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    key: str
    number_of_samples: int
    numerator_denominator_sum_product: float | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None
    sum: float
    sum_squares: float


class ExperimentStatsBaseValidated(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    key: str
    number_of_samples: int
    numerator_denominator_sum_product: float | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None
    sum: float
    sum_squares: float
    validation_failures: list[ExperimentStatsValidationFailure] | None = None


class ExperimentVariantResultBayesian(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chance_to_win: float | None = None
    credible_interval: list[float] | None = Field(default=None, max_length=2, min_length=2)
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    key: str
    method: Literal["bayesian"] = "bayesian"
    number_of_samples: int
    numerator_denominator_sum_product: float | None = None
    significant: bool | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None
    sum: float
    sum_squares: float
    validation_failures: list[ExperimentStatsValidationFailure] | None = None


class ExperimentVariantResultFrequentist(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    confidence_interval: list[float] | None = Field(default=None, max_length=2, min_length=2)
    denominator_sum: float | None = None
    denominator_sum_squares: float | None = None
    key: str
    method: Literal["frequentist"] = "frequentist"
    number_of_samples: int
    numerator_denominator_sum_product: float | None = None
    p_value: float | None = None
    significant: bool | None = None
    step_counts: list[int] | None = None
    step_sessions: list[list[SessionData]] | None = None
    sum: float
    sum_squares: float
    validation_failures: list[ExperimentStatsValidationFailure] | None = None


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
    label: str | None = None
    operator: PropertyOperator
    type: Literal["feature"] = Field(default="feature", description='Event property with "$feature/" prepended')
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


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


class GroupPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int | None = None
    key: str
    label: str | None = None
    operator: PropertyOperator
    type: Literal["group"] = "group"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class HogQLAutocompleteResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incomplete_list: bool = Field(..., description="Whether or not the suggestions returned are complete")
    suggestions: list[AutocompleteCompletionItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class HogQLNotice(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    end: int | None = None
    fix: str | None = None
    message: str
    start: int | None = None


class HogQLPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: str | None = None
    type: Literal["hogql"] = "hogql"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class HogQLQueryModifiers(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    optimizeProjections: bool | None = None
    personsArgMaxVersion: PersonsArgMaxVersion | None = None
    personsJoinMode: PersonsJoinMode | None = None
    personsOnEventsMode: PersonsOnEventsMode | None = None
    propertyGroupsMode: PropertyGroupsMode | None = None
    s3TableUseInvalidColumns: bool | None = None
    sessionTableVersion: SessionTableVersion | None = None
    sessionsV2JoinMode: SessionsV2JoinMode | None = None
    timings: bool | None = None
    useMaterializedViews: bool | None = None
    usePreaggregatedTableTransforms: bool | None = Field(
        default=None,
        description="Try to automatically convert HogQL queries to use preaggregated tables at the AST level *",
    )
    usePresortedEventsTable: bool | None = None
    useWebAnalyticsPreAggregatedTables: bool | None = None


class HogQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: str | None = None
    kind: Literal["HogQuery"] = "HogQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: HogQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    bounds: InsightsThresholdBounds | None = None
    type: InsightThresholdType


class LLMTrace(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aiSessionId: str | None = None
    createdAt: str
    events: list[LLMTraceEvent]
    id: str
    inputCost: float | None = None
    inputState: Any | None = None
    inputTokens: float | None = None
    outputCost: float | None = None
    outputState: Any | None = None
    outputTokens: float | None = None
    person: LLMTracePerson
    totalCost: float | None = None
    totalLatency: float | None = None
    traceName: str | None = None


class LifecycleFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    showLegend: bool | None = False
    showValuesOnSeries: bool | None = None
    stacked: bool | None = True
    toggledLifecycles: list[LifecycleToggle] | None = None


class LifecycleFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    show_legend: bool | None = None
    show_values_on_series: bool | None = None
    toggledLifecycles: list[LifecycleToggle] | None = None


class LogEntryPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: str | None = None
    operator: PropertyOperator
    type: Literal["log_entry"] = "log_entry"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


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
    label: str | None = None
    operator: PropertyOperator
    type: Literal["log"] = "log"
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


class MarketingAnalyticsItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: float | None = None
    hasComparison: bool | None = None
    isIncreaseBad: bool | None = None
    key: str
    kind: WebAnalyticsItemKind
    previous: Union[float, str] | None = None
    value: Union[float, str] | None = None


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
    session_id: str | None = None


class MaxBillingContextBillingPeriod(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    current_period_end: str
    current_period_start: str
    interval: MaxBillingContextBillingPeriodInterval


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
    conversation_notebooks: list[DeepResearchNotebook] | None = None
    current_run_notebooks: list[DeepResearchNotebook] | None = None
    id: str | None = None
    notebook_id: str
    notebook_type: Literal["deep_research"] = "deep_research"
    parent_tool_call_id: str | None = None
    tool_calls: list[AssistantToolCall] | None = None
    type: Literal["ai/notebook"] = "ai/notebook"


class PathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    edgeLimit: int | None = 50
    endPoint: str | None = None
    excludeEvents: list[str] | None = None
    includeEventTypes: list[PathType] | None = None
    localPathCleaningFilters: list[PathCleaningFilter] | None = None
    maxEdgeWeight: int | None = None
    minEdgeWeight: int | None = None
    pathDropoffKey: str | None = Field(default=None, description="Relevant only within actors query")
    pathEndKey: str | None = Field(default=None, description="Relevant only within actors query")
    pathGroupings: list[str] | None = None
    pathReplacements: bool | None = None
    pathStartKey: str | None = Field(default=None, description="Relevant only within actors query")
    pathsHogQLExpression: str | None = None
    startPoint: str | None = None
    stepLimit: int | None = 5


class PersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: str | None = None
    operator: PropertyOperator
    type: Literal["person"] = Field(default="person", description="Person properties")
    value: Union[list[Union[str, float, bool]], Union[str, float, bool]] | None = None


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
    ch_table_names: list[str] | None = None
    errors: list[HogQLNotice]
    isUsingIndices: QueryIndexUsage | None = None
    isValid: bool | None = None
    notices: list[HogQLNotice]
    query: str | None = None
    table_names: list[str] | None = None
    warnings: list[HogQLNotice]


class QueryResponseAlternative9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incomplete_list: bool = Field(..., description="Whether or not the suggestions returned are complete")
    suggestions: list[AutocompleteCompletionItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative27(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: dict[str, Any]
    error: ExternalQueryError | None = None
    status: ExternalQueryStatus


class QueryStatus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    complete: bool | None = Field(
        default=False,
        description=(
            "Whether the query is still running. Will be true if the query is complete, even if it errored. Either"
            " result or error will be set."
        ),
    )
    dashboard_id: int | None = None
    end_time: datetime | None = Field(
        default=None, description="When did the query execution task finish (whether successfully or not)."
    )
    error: bool | None = Field(
        default=False,
        description=(
            "If the query failed, this will be set to true. More information can be found in the error_message field."
        ),
    )
    error_message: str | None = None
    expiration_time: datetime | None = None
    id: str
    insight_id: int | None = None
    labels: list[str] | None = None
    pickup_time: datetime | None = Field(
        default=None, description="When was the query execution task picked up by a worker."
    )
    query_async: Literal[True] = Field(default=True, description="ONLY async queries use QueryStatus.")
    query_progress: ClickhouseQueryProgress | None = None
    results: Any | None = None
    start_time: datetime | None = Field(default=None, description="When was query execution task enqueued.")
    task_id: str | None = None
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
    label: str | None = None


class RevenueAnalyticsAssistantFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    date_from: str | None = None
    date_to: str | None = None
    properties: list[RevenueAnalyticsPropertyFilter]


class RevenueAnalyticsEventItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    couponProperty: str | None = Field(
        default=None,
        description=(
            "Property used to identify whether the revenue event is connected to a coupon Useful when trying to break"
            " revenue down by a specific coupon"
        ),
    )
    currencyAwareDecimal: bool | None = Field(
        default=False,
        description=(
            "If true, the revenue will be divided by the smallest unit of the currency.\n\nFor example, in case this is"
            " set to true, if the revenue is 1089 and the currency is USD, the revenue will be $10.89, but if the"
            " currency is JPY, the revenue will be ¥1089."
        ),
    )
    eventName: str
    productProperty: str | None = Field(
        default=None,
        description=(
            "Property used to identify what product the revenue event refers to Useful when trying to break revenue"
            " down by a specific product"
        ),
    )
    revenueCurrencyProperty: RevenueCurrencyPropertyConfig | None = Field(
        default_factory=lambda: RevenueCurrencyPropertyConfig.model_validate({"static": "USD"}),
        description=(
            "TODO: In the future, this should probably be renamed to `currencyProperty` to follow the pattern above"
        ),
    )
    revenueProperty: str
    subscriptionDropoffDays: float | None = Field(
        default=45,
        description=(
            "The number of days we still consider a subscription to be active after the last event. This is useful to"
            " avoid the current month's data to look as if most of the subscriptions have churned since we might not"
            " have an event for the current month."
        ),
    )
    subscriptionDropoffMode: SubscriptionDropoffMode | None = Field(
        default=SubscriptionDropoffMode.LAST_EVENT,
        description=(
            "After a subscription has dropped off, when should we consider it to have ended? It should either be at the"
            " date of the last event (will alter past periods, the default), or at the date of the last event plus the"
            " dropoff period."
        ),
    )
    subscriptionProperty: str | None = Field(
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
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
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
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RevenueExampleDataWarehouseTablesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class RevenueExampleEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class SavedInsightNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    allowSorting: bool | None = Field(
        default=None, description="Can the user click on column headers to sort the table? (default: true)"
    )
    context: DataTableNodeViewPropsContext | None = Field(
        default=None, description="Context for the table, used by components like ColumnConfigurator"
    )
    defaultColumns: list[str] | None = Field(
        default=None, description="Default columns to use when resetting column configuration"
    )
    embedded: bool | None = Field(default=None, description="Query is embedded inside another bordered component")
    expandable: bool | None = Field(default=None, description="Can expand row to show raw event data (default: true)")
    full: bool | None = Field(default=None, description="Show with most visual options enabled. Used in insight scene.")
    hidePersonsModal: bool | None = None
    hideTooltipOnScroll: bool | None = None
    kind: Literal["SavedInsightNode"] = "SavedInsightNode"
    propertiesViaUrl: bool | None = Field(default=None, description="Link properties via the URL (default: false)")
    shortId: str
    showActions: bool | None = Field(default=None, description="Show the kebab menu at the end of the row")
    showColumnConfigurator: bool | None = Field(
        default=None, description="Show a button to configure the table's columns if possible"
    )
    showCorrelationTable: bool | None = None
    showDateRange: bool | None = Field(default=None, description="Show date range selector")
    showElapsedTime: bool | None = Field(default=None, description="Show the time it takes to run a query")
    showEventFilter: bool | None = Field(
        default=None, description="Include an event filter above the table (EventsNode only)"
    )
    showExport: bool | None = Field(default=None, description="Show the export button")
    showFilters: bool | None = None
    showHeader: bool | None = None
    showHogQLEditor: bool | None = Field(default=None, description="Include a HogQL query editor above HogQL tables")
    showLastComputation: bool | None = None
    showLastComputationRefresh: bool | None = None
    showOpenEditorButton: bool | None = Field(
        default=None, description="Show a button to open the current query as a new insight. (default: true)"
    )
    showPersistentColumnConfigurator: bool | None = Field(
        default=None, description="Show a button to configure and persist the table's default columns if possible"
    )
    showPropertyFilter: Union[bool, list[TaxonomicFilterGroupType]] | None = Field(
        default=None, description="Include a property filter above the table"
    )
    showReload: bool | None = Field(default=None, description="Show a reload button")
    showResults: bool | None = None
    showResultsTable: bool | None = Field(default=None, description="Show a results table")
    showSavedFilters: bool | None = Field(
        default=None, description="Show saved filters feature for this table (requires uniqueKey)"
    )
    showSavedQueries: bool | None = Field(default=None, description="Shows a list of saved queries")
    showSearch: bool | None = Field(default=None, description="Include a free text search field (PersonsNode only)")
    showTable: bool | None = None
    showTestAccountFilters: bool | None = Field(default=None, description="Show filter to exclude test accounts")
    showTimings: bool | None = Field(default=None, description="Show a detailed query timing breakdown")
    suppressSessionAnalysisWarning: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")
    vizSpecificOptions: VizSpecificOptions | None = None


class Filters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    properties: list[SessionPropertyFilter] | None = None


class SessionAttributionExplorerQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class SessionBatchEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    session_events: list[SessionEventsItem] | None = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    sessions_with_no_events: list[str] | None = Field(
        default=None, description="List of session IDs that had no matching events"
    )
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class SessionRecordingType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active_seconds: float | None = None
    activity_score: float | None = Field(
        default=None, description="calculated on the backend so that we can sort by it, definition may change over time"
    )
    click_count: float | None = None
    console_error_count: float | None = None
    console_log_count: float | None = None
    console_warn_count: float | None = None
    distinct_id: str | None = None
    email: str | None = None
    end_time: str = Field(..., description="When the recording ends in ISO format.")
    expiry_time: str | None = Field(default=None, description="When the recording expires, in ISO format.")
    id: str
    inactive_seconds: float | None = None
    keypress_count: float | None = None
    matching_events: list[MatchedRecording] | None = Field(default=None, description="List of matching events. *")
    mouse_activity_count: float | None = Field(
        default=None, description="count of all mouse activity in the recording, not just clicks"
    )
    ongoing: bool | None = Field(
        default=None,
        description=(
            "whether we have received data for this recording in the last 5 minutes (assumes the recording was loaded"
            " from ClickHouse)\n*"
        ),
    )
    person: PersonType | None = None
    recording_duration: float = Field(..., description="Length of recording in seconds.")
    recording_ttl: float | None = Field(
        default=None, description="Number of whole days left until the recording expires."
    )
    retention_period_days: float | None = Field(default=None, description="retention period for this recording")
    snapshot_source: SnapshotSource
    start_time: str = Field(..., description="When the recording starts in ISO format.")
    start_url: str | None = None
    storage: Storage | None = Field(default=None, description="Where this recording information was loaded from")
    summary: str | None = None
    viewed: bool = Field(..., description="Whether this recording has been viewed by you already.")
    viewers: list[str] = Field(..., description="user ids of other users who have viewed this recording")


class SessionsTimelineQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TimelineEntry]
    timings: list[QueryTiming] | None = Field(
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
    computedAs: StickinessComputationMode | None = None
    display: ChartDisplayType | None = None
    hiddenLegendIndexes: list[int] | None = None
    resultCustomizationBy: ResultCustomizationBy | None = Field(
        default=ResultCustomizationBy.VALUE,
        description="Whether result datasets are associated by their values or by their order.",
    )
    resultCustomizations: (
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]] | None
    ) = Field(default=None, description="Customizations for the appearance of result datasets.")
    showLegend: bool | None = None
    showMultipleYAxes: bool | None = None
    showValuesOnSeries: bool | None = None
    stickinessCriteria: StickinessCriteria | None = None


class StickinessQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class SuggestedQuestionsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["SuggestedQuestionsQuery"] = "SuggestedQuestionsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: SuggestedQuestionsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class SurveyAnalysisQuestionGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    questionId: str | None = Field(default="unknown", description="Question identifier")
    questionName: str | None = Field(default="Unknown question", description="Question text")
    responses: list[SurveyAnalysisResponseItem] | None = Field(
        default=[], description="List of responses for this question"
    )


class SurveyAppearanceSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class SurveyDisplayConditionsSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions: Actions | None = None
    deviceTypes: list[str] | None = None
    deviceTypesMatchType: SurveyMatchType | None = None
    linkedFlagVariant: str | None = None
    seenSurveyWaitPeriodInDays: float | None = None
    selector: str | None = None
    url: str | None = None
    urlMatchType: SurveyMatchType | None = None


class SurveyQuestionSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    question: str
    scale: float | None = None
    shuffleOptions: bool | None = None
    type: SurveyQuestionType
    upperBoundLabel: str | None = None


class TableSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[ChartAxis] | None = None
    conditionalFormatting: list[ConditionalFormattingRule] | None = None


class TaskExecutionItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    artifact_ids: list[str] | None = None
    description: str
    id: str
    progress_text: str | None = None
    prompt: str
    status: TaskExecutionStatus
    task_type: str


class TaskExecutionMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str | None = None
    parent_tool_call_id: str | None = None
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
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TestCachedBasicQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TraceQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TracesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TrendsAlertConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    check_ongoing_interval: bool | None = None
    series_index: int
    type: Literal["TrendsAlertConfig"] = "TrendsAlertConfig"


class TrendsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregationAxisFormat: AggregationAxisFormat | None = AggregationAxisFormat.NUMERIC
    aggregationAxisPostfix: str | None = None
    aggregationAxisPrefix: str | None = None
    breakdown_histogram_bin_count: float | None = None
    confidenceLevel: float | None = None
    decimalPlaces: float | None = None
    detailedResultsAggregationType: DetailedResultsAggregationType | None = Field(
        default=None, description="detailed results table"
    )
    display: ChartDisplayType | None = ChartDisplayType.ACTIONS_LINE_GRAPH
    formula: str | None = None
    formulaNodes: list[TrendsFormulaNode] | None = Field(
        default=None,
        description="List of formulas with optional custom names. Takes precedence over formula/formulas if set.",
    )
    formulas: list[str] | None = None
    goalLines: list[GoalLine] | None = Field(default=None, description="Goal Lines")
    hiddenLegendIndexes: list[int] | None = None
    minDecimalPlaces: float | None = None
    movingAverageIntervals: float | None = None
    resultCustomizationBy: ResultCustomizationBy | None = Field(
        default=ResultCustomizationBy.VALUE,
        description="Wether result datasets are associated by their values or by their order.",
    )
    resultCustomizations: (
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]] | None
    ) = Field(default=None, description="Customizations for the appearance of result datasets.")
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


class TrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = Field(default=None, description="Wether more breakdown values are available.")
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class UsageMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    change_from_previous_pct: float | None = None
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
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[UsageMetric]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebAnalyticsExternalSummaryQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    data: dict[str, Any]
    error: ExternalQueryError | None = None
    status: ExternalQueryStatus


class WebAnalyticsItemBaseNumberString(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: float | None = None
    isIncreaseBad: bool | None = None
    key: str
    kind: WebAnalyticsItemKind
    previous: Union[float, str] | None = None
    value: Union[float, str] | None = None


class WebAnalyticsItemBaseNumber(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    changeFromPreviousPct: float | None = None
    isIncreaseBad: bool | None = None
    key: str
    kind: WebAnalyticsItemKind
    previous: float | None = None
    value: float | None = None


class WebExternalClicksTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class WebGoalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class WebOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: bool | None = None


class WebPageURLSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PageURL]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebStatsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


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
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ActorsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str] | None = None


class AnalyticsQueryResponseBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class AssistantFunnelNodeShared(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    math: AssistantFunnelsMath | None = Field(
        default=None,
        description=(
            "Optional math aggregation type for the series. Only specify this math type if the user wants one of these."
            " `first_time_for_user` - counts the number of users who have completed the event for the first time ever."
            " `first_time_for_user_with_filters` - counts the number of users who have completed the event with"
            " specified filters for the first time."
        ),
    )
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


class AssistantFunnelsActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: float = Field(..., description="Action ID from the plan.")
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: AssistantFunnelsMath | None = Field(
        default=None,
        description=(
            "Optional math aggregation type for the series. Only specify this math type if the user wants one of these."
            " `first_time_for_user` - counts the number of users who have completed the event for the first time ever."
            " `first_time_for_user_with_filters` - counts the number of users who have completed the event with"
            " specified filters for the first time."
        ),
    )
    name: str = Field(..., description="Action name from the plan.")
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
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class AssistantFunnelsEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = Field(
        default=None, description="Optional custom name for the event if it is needed to be renamed."
    )
    event: str = Field(..., description="Name of the event.")
    kind: Literal["EventsNode"] = "EventsNode"
    math: AssistantFunnelsMath | None = Field(
        default=None,
        description=(
            "Optional math aggregation type for the series. Only specify this math type if the user wants one of these."
            " `first_time_for_user` - counts the number of users who have completed the event for the first time ever."
            " `first_time_for_user_with_filters` - counts the number of users who have completed the event with"
            " specified filters for the first time."
        ),
    )
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
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class AssistantFunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(
        default=None,
        description=(
            "Use this field to define the aggregation by a specific group from the provided group mapping, which is NOT"
            " users or sessions."
        ),
    )
    breakdownFilter: AssistantFunnelsBreakdownFilter | None = Field(
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
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelsFilter: AssistantFunnelsFilter | None = Field(
        default=None, description="Properties specific to the funnels insight"
    )
    interval: IntervalType | None = Field(
        default=None, description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`"
    )
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
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
    ) = Field(default=[], description="Property filters for all series")
    samplingFactor: float | None = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )
    series: list[Union[AssistantFunnelsEventsNode, AssistantFunnelsActionsNode]] = Field(
        ..., description="Events or actions to include. Prioritize the more popular and fresh events and actions."
    )


class AssistantInsightsQueryBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
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
    ) = Field(default=[], description="Property filters for all series")
    samplingFactor: float | None = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )


class AssistantMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: str | None = None
    meta: AssistantMessageMetadata | None = None
    parent_tool_call_id: str | None = None
    tool_calls: list[AssistantToolCall] | None = None
    type: Literal["ai"] = "ai"


class AssistantRetentionFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: bool | None = Field(
        default=None,
        description=(
            "Whether retention should be rolling (aka unbounded, cumulative). Rolling retention means that a user"
            " coming back in period 5 makes them count towards all the previous periods."
        ),
    )
    meanRetentionCalculation: MeanRetentionCalculation | None = Field(
        default=None,
        description=(
            "Whether an additional series should be shown, showing the mean conversion for each period across cohorts."
        ),
    )
    period: RetentionPeriod | None = Field(
        default=RetentionPeriod.DAY, description="Retention period, the interval to track cohorts by."
    )
    retentionReference: RetentionReference | None = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retentionType: RetentionType | None = Field(
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
    totalIntervals: int | None = Field(
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
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: Literal["RetentionQuery"] = "RetentionQuery"
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
    ) = Field(default=[], description="Property filters for all series")
    retentionFilter: AssistantRetentionFilter = Field(..., description="Properties specific to the retention insight")
    samplingFactor: float | None = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )


class AssistantTrendsActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = None
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
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
    name: str = Field(..., description="Action name from the plan.")
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
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class AssistantTrendsEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = None
    event: str | None = Field(default=None, description="The event or `null` for all events.")
    kind: Literal["EventsNode"] = "EventsNode"
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
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class AssistantTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownFilter: AssistantTrendsBreakdownFilter | None = Field(
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
    compareFilter: CompareFilter | None = Field(default=None, description="Compare to date range")
    dateRange: Union[AssistantDateRange, AssistantDurationRange] | None = Field(
        default=None, description="Date range for the query"
    )
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: IntervalType | None = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["TrendsQuery"] = "TrendsQuery"
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
    ) = Field(default=[], description="Property filters for all series")
    samplingFactor: float | None = Field(
        default=None, description="Sampling rate from 0 to 1 where 1 is 100% of the data."
    )
    series: list[Union[AssistantTrendsEventsNode, AssistantTrendsActionsNode]] = Field(
        ..., description="Events or actions to include. Prioritize the more popular and fresh events and actions."
    )
    trendsFilter: AssistantTrendsFilter | None = Field(
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
    cache_key: str | None = None
    query_status: QueryStatus | None = None


class CachedActorsPropertyTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedActorsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str] | None = None


class CachedCalendarHeatmapQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = Field(default=None, description="Wether more breakdown values are available.")
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: EventsHeatMapStructuredResult
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedDocumentSimilarityQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EmbeddingDistance]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedErrorTrackingSimilarIssuesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[SimilarIssue]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedEventTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EventTaxonomyItem]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedExperimentExposureQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    date_range: DateRange
    is_cached: bool
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
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
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: FunnelCorrelationResult
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class CachedFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    isUdf: bool | None = None
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedGroupsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    last_refresh: datetime
    limit: int
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedLifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedLogsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedMarketingAnalyticsAggregatedQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: SamplingRate | None = None
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedMarketingAnalyticsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: SamplingRate | None = None
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class CachedNewExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: ExperimentStatsBaseValidated
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timezone: str
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]]


class CachedPathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PathsLink]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedRevenueExampleDataWarehouseTablesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class CachedRevenueExampleEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class CachedSessionAttributionExplorerQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class CachedSessionBatchEventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    session_events: list[SessionEventsItem] | None = Field(
        default=None, description="Events grouped by session ID. Only populated when group_by_session=True."
    )
    sessions_with_no_events: list[str] | None = Field(
        default=None, description="List of session IDs that had no matching events"
    )
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class CachedSessionsTimelineQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TimelineEntry]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedStickinessQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedSuggestedQuestionsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    questions: list[str]
    timezone: str


class CachedTeamTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TeamTaxonomyItem]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTraceQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTracesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = Field(default=None, description="Wether more breakdown values are available.")
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedUsageMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[UsageMetric]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedVectorSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[VectorSearchResponseItem]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebExternalClicksTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class CachedWebGoalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class CachedWebOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: SamplingRate | None = None
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: bool | None = None


class CachedWebPageURLSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PageURL]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebStatsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


class CachedWebVitalsPathBreakdownQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CalendarHeatmapResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = Field(default=None, description="Wether more breakdown values are available.")
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: EventsHeatMapStructuredResult
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ConversionGoalFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: str | None = None
    event: str | None = Field(default=None, description="The event or `null` for all events.")
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsNode"] = "EventsNode"
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
    orderBy: list[str] | None = Field(default=None, description="Columns to order by")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    schema_map: dict[str, Union[str, Any]]
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ConversionGoalFilter2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    schema_map: dict[str, Union[str, Any]]
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ConversionGoalFilter3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: str | None = None
    distinct_id_field: str
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    schema_map: dict[str, Union[str, Any]]
    table_name: str
    timestamp_field: str
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class DashboardFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class Response(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class Response1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str] | None = None


class Response2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class Response4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: bool | None = None


class Response5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


class Response6(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class Response8(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response9(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class Response10(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response11(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response12(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response13(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response14(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response15(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class Response17(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class Response18(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response23(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class DataWarehouseNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = None
    distinct_id_field: str
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    table_name: str
    timestamp_field: str
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class DatabaseSchemaBatchExportTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    row_count: float | None = None
    type: Literal["batch_export"] = "batch_export"


class DatabaseSchemaDataWarehouseTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    format: str
    id: str
    name: str
    row_count: float | None = None
    schema_: DatabaseSchemaSchema | None = Field(default=None, alias="schema")
    source: DatabaseSchemaSource | None = None
    type: Literal["data_warehouse"] = "data_warehouse"
    url_pattern: str


class DocumentSimilarityQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EmbeddingDistance]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class EndpointRunRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    client_query_id: str | None = Field(
        default=None, description="Client provided query ID. Can be used to retrieve the status or cancel the query."
    )
    filters_override: DashboardFilter | None = None
    query_override: dict[str, Any] | None = None
    refresh: RefreshType | None = Field(
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
    variables_override: dict[str, dict[str, Any]] | None = None
    variables_values: dict[str, Any] | None = None


class EntityNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: NodeKind
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    aggregations: ErrorTrackingIssueAggregations | None = None
    assignee: ErrorTrackingIssueAssignee | None = None
    description: str | None = None
    external_issues: list[ErrorTrackingExternalReference] | None = None
    first_event: FirstEvent | None = None
    first_seen: datetime
    id: str
    last_event: LastEvent | None = None
    last_seen: datetime
    library: str | None = None
    name: str | None = None
    revenue: float | None = None
    status: Status


class ErrorTrackingIssueFilteringToolOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    orderBy: OrderBy1
    orderDirection: OrderDirection1 | None = None
    removedFilterIndexes: list[int] | None = None
    searchQuery: str | None = None
    status: Status2 | None = None


class ErrorTrackingQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ErrorTrackingRelationalIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignee: ErrorTrackingIssueAssignee | None = None
    description: str | None = None
    external_issues: list[ErrorTrackingExternalReference] | None = None
    first_seen: datetime
    id: str
    name: str | None = None
    status: Status4


class ErrorTrackingSimilarIssuesQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[SimilarIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class EventTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EventTaxonomyItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class EventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = None
    event: str | None = Field(default=None, description="The event or `null` for all events.")
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsNode"] = "EventsNode"
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
    orderBy: list[str] | None = Field(default=None, description="Columns to order by")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class EventsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class ExperimentDataWarehouseNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = None
    data_warehouse_join_key: str
    events_join_key: str
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["ExperimentDataWarehouseNode"] = "ExperimentDataWarehouseNode"
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    table_name: str
    timestamp_field: str
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    response: dict[str, Any] | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class FeatureFlagGroupType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
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
    rollout_percentage: float | None = None
    sort_key: str | None = None
    users_affected: float | None = None
    variant: str | None = None


class FunnelCorrelationResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: FunnelCorrelationResult
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class FunnelExclusionActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    funnelFromStep: int
    funnelToStep: int
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class FunnelExclusionEventsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    custom_name: str | None = None
    event: str | None = Field(default=None, description="The event or `null` for all events.")
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    funnelFromStep: int
    funnelToStep: int
    kind: Literal["EventsNode"] = "EventsNode"
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
    orderBy: list[str] | None = Field(default=None, description="Columns to order by")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class FunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    isUdf: bool | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class GenericCachedQueryResponse(BaseModel):
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    timezone: str


class GroupsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class HeatMapQuerySource(RootModel[EventsNode]):
    root: EventsNode


class HogQLFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class HogQLMetadataResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ch_table_names: list[str] | None = None
    errors: list[HogQLNotice]
    isUsingIndices: QueryIndexUsage | None = None
    isValid: bool | None = None
    notices: list[HogQLNotice]
    query: str | None = None
    table_names: list[str] | None = None
    warnings: list[HogQLNotice]


class HogQLQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: str | None = Field(default=None, description="Executed ClickHouse query")
    columns: list | None = Field(default=None, description="Returned columns")
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: list[str] | None = Field(default=None, description="Query explanation output")
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = Field(default=None, description="Query metadata output")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query: str | None = Field(default=None, description="Input query string")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = Field(default=None, description="Types of returned columns")


class InsightActorsQueryBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    includeRecordings: bool | None = None
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: ActorsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class LifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class LogsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class MarketingAnalyticsAggregatedQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class MarketingAnalyticsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    attribution_mode: AttributionMode | None = None
    attribution_window_days: float | None = None
    campaign_name_mappings: dict[str, dict[str, list[str]]] | None = None
    conversion_goals: list[Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3]] | None = None
    sources_map: dict[str, SourceMap] | None = None


class MarketingAnalyticsTableQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class MaxBillingContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    billing_period: MaxBillingContextBillingPeriod | None = None
    billing_plan: str | None = None
    has_active_subscription: bool
    is_deactivated: bool | None = None
    products: list[MaxProductInfo]
    projected_total_amount_usd: str | None = None
    projected_total_amount_usd_after_discount: str | None = None
    projected_total_amount_usd_with_limit: str | None = None
    projected_total_amount_usd_with_limit_after_discount: str | None = None
    settings: MaxBillingContextSettings
    spend_history: list[SpendHistoryItem] | None = None
    startup_program_label: str | None = None
    startup_program_label_previous: str | None = None
    subscription_level: MaxBillingContextSubscriptionLevel
    total_current_amount_usd: str | None = None
    trial: MaxBillingContextTrial | None = None
    usage_history: list[UsageHistoryItem] | None = None


class MultipleBreakdownOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    values: list[BreakdownItem]


class PathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PathsLink]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class PersonsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["PersonsNode"] = "PersonsNode"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    search: str | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class PlanningMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str | None = None
    parent_tool_call_id: str | None = None
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
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str] | None = None


class QueryResponseAlternative3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[BreakdownItem] | None = None
    breakdowns: list[MultipleBreakdownOptions] | None = None
    compare: list[CompareItem] | None = None
    day: list[DayItem] | None = None
    interval: list[IntervalItem] | None = None
    series: list[Series] | None = None
    status: list[StatusItem] | None = None


class QueryResponseAlternative5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TimelineEntry]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative7(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: str | None = Field(default=None, description="Executed ClickHouse query")
    columns: list | None = Field(default=None, description="Returned columns")
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: list[str] | None = Field(default=None, description="Query explanation output")
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = Field(default=None, description="Query metadata output")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query: str | None = Field(default=None, description="Input query string")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = Field(default=None, description="Types of returned columns")


class QueryResponseAlternative10(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative13(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative14(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[SimilarIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative20(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EmbeddingDistance]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative21(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: bool | None = None


class QueryResponseAlternative22(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


class QueryResponseAlternative23(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative25(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative26(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PageURL]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative28(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative29(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative30(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative31(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative32(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative33(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative34(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative35(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative36(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    limit: int
    missing_actors_count: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str] | None = None


class QueryResponseAlternative37(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str = Field(..., description="Generated HogQL query.")
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list[str]


class QueryResponseAlternative38(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: str | None = Field(default=None, description="Executed ClickHouse query")
    columns: list | None = Field(default=None, description="Returned columns")
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: list[str] | None = Field(default=None, description="Query explanation output")
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = Field(default=None, description="Query metadata output")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query: str | None = Field(default=None, description="Input query string")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = Field(default=None, description="Types of returned columns")


class QueryResponseAlternative39(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateFrom: str | None = None
    dateTo: str | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebOverviewItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    usedPreAggregatedTables: bool | None = None


class QueryResponseAlternative40(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None
    usedPreAggregatedTables: bool | None = None


class QueryResponseAlternative41(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative43(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative44(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative45(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative46(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative47(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsMRRQueryResultItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative48(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RevenueAnalyticsOverviewItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative49(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative50(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative52(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[list[MarketingAnalyticsItem]]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative53(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: dict[str, MarketingAnalyticsItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative54(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative58(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative59(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = Field(default=None, description="Wether more breakdown values are available.")
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative60(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    isUdf: bool | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative62(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[PathsLink]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative63(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[dict[str, Any]]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative65(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: FunnelCorrelationResult
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = None


class QueryResponseAlternative67(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Any
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative69(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TeamTaxonomyItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative70(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[EventTaxonomyItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative71(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: Union[ActorsPropertyTaxonomyResponse, list[ActorsPropertyTaxonomyResponse]]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative72(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[LLMTrace]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative74(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[VectorSearchResponseItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative75(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[UsageMetric]
    timings: list[QueryTiming] | None = Field(
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
    ) = Field(default=None, description="filters on the event")
    type: EntityType | None = None
    uuid: str | None = None


class RetentionFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: bool | None = None
    dashboardDisplay: RetentionDashboardDisplayType | None = None
    display: ChartDisplayType | None = Field(default=None, description="controls the display of the retention graph")
    meanRetentionCalculation: MeanRetentionCalculation | None = None
    minimumOccurrences: int | None = None
    period: RetentionPeriod | None = RetentionPeriod.DAY
    retentionReference: RetentionReference | None = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retentionType: RetentionType | None = None
    returningEntity: RetentionEntity | None = None
    showTrendLines: bool | None = None
    targetEntity: RetentionEntity | None = None
    timeWindowMode: TimeWindowMode | None = Field(
        default=None, description="The time window mode to use for retention calculations"
    )
    totalIntervals: int | None = 8


class RetentionFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: bool | None = None
    mean_retention_calculation: MeanRetentionCalculation | None = None
    period: RetentionPeriod | None = None
    retention_reference: RetentionReference | None = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retention_type: RetentionType | None = None
    returning_entity: RetentionEntity | None = None
    show_mean: bool | None = None
    target_entity: RetentionEntity | None = None
    total_intervals: int | None = None


class RetentionResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_value: Union[str, float] | None = Field(
        default=None, description="Optional breakdown value for retention cohorts"
    )
    date: datetime
    label: str
    values: list[RetentionValue]


class RevenueAnalyticsBaseQueryRevenueAnalyticsGrossRevenueQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsGrossRevenueQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsMRRQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsMRRQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsMetricsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsMetricsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsOverviewQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsOverviewQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsBaseQueryRevenueAnalyticsTopCustomersQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsTopCustomersQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[RevenueAnalyticsEventItem] | None = []
    filter_test_accounts: bool | None = False
    goals: list[RevenueAnalyticsGoal] | None = []


class RevenueAnalyticsGrossRevenueQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: DateRange | None = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsGrossRevenueQuery"] = "RevenueAnalyticsGrossRevenueQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsGrossRevenueQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsMRRQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: DateRange | None = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMRRQuery"] = "RevenueAnalyticsMRRQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsMRRQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsMetricsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    dateRange: DateRange | None = None
    interval: SimpleIntervalType
    kind: Literal["RevenueAnalyticsMetricsQuery"] = "RevenueAnalyticsMetricsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsMetricsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsOverviewQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    kind: Literal["RevenueAnalyticsOverviewQuery"] = "RevenueAnalyticsOverviewQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsOverviewQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueAnalyticsTopCustomersQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    groupBy: RevenueAnalyticsTopCustomersGroupBy
    kind: Literal["RevenueAnalyticsTopCustomersQuery"] = "RevenueAnalyticsTopCustomersQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[RevenueAnalyticsPropertyFilter]
    response: RevenueAnalyticsTopCustomersQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueExampleDataWarehouseTablesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["RevenueExampleDataWarehouseTablesQuery"] = "RevenueExampleDataWarehouseTablesQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    response: RevenueExampleDataWarehouseTablesQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RevenueExampleEventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["RevenueExampleEventsQuery"] = "RevenueExampleEventsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    response: RevenueExampleEventsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class SessionAttributionExplorerQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    filters: Filters | None = None
    groupBy: list[SessionAttributionGroupBy]
    kind: Literal["SessionAttributionExplorerQuery"] = "SessionAttributionExplorerQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    response: SessionAttributionExplorerQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class SessionsTimelineQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after: str | None = Field(
        default=None, description="Only fetch sessions that started after this timestamp (default: '-24h')"
    )
    before: str | None = Field(
        default=None, description="Only fetch sessions that started before this timestamp (default: '+5s')"
    )
    kind: Literal["SessionsTimelineQuery"] = "SessionsTimelineQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    personId: str | None = Field(default=None, description="Fetch sessions only for a given person")
    response: SessionsTimelineQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class SurveyCreationSchema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    appearance: SurveyAppearanceSchema | None = None
    archived: bool | None = None
    conditions: SurveyDisplayConditionsSchema | None = None
    description: str
    enable_partial_responses: bool | None = None
    end_date: str | None = None
    iteration_count: float | None = None
    iteration_frequency_days: float | None = None
    linked_flag_id: float | None = None
    name: str
    questions: list[SurveyQuestionSchema]
    responses_limit: float | None = None
    should_launch: bool | None = None
    start_date: str | None = None
    type: SurveyType


class TeamTaxonomyQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[TeamTaxonomyItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class TileFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class TraceQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    kind: Literal["TraceQuery"] = "TraceQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: TraceQueryResponse | None = None
    tags: QueryLogTags | None = None
    traceId: str
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class TracesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    filterTestAccounts: bool | None = None
    kind: Literal["TracesQuery"] = "TracesQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    personId: str | None = Field(default=None, description="Person who performed the event")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: TracesQueryResponse | None = None
    showColumnConfigurator: bool | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class UsageMetricsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_key: str | None = Field(
        default=None, description="Group key. Required with group_type_index for group queries."
    )
    group_type_index: int | None = Field(
        default=None, description="Group type index. Required with group_key for group queries."
    )
    kind: Literal["UsageMetricsQuery"] = "UsageMetricsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    person_id: str | None = Field(
        default=None, description="Person ID to fetch metrics for. Mutually exclusive with group parameters."
    )
    response: UsageMetricsQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class VectorSearchQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[VectorSearchResponseItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebAnalyticsExternalSummaryQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    kind: Literal["WebAnalyticsExternalSummaryQuery"] = "WebAnalyticsExternalSummaryQuery"
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebAnalyticsExternalSummaryQueryResponse | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebExternalClicksTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    kind: Literal["WebExternalClicksTableQuery"] = "WebExternalClicksTableQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebExternalClicksTableQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    stripQueryParams: bool | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebGoalsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    kind: Literal["WebGoalsQuery"] = "WebGoalsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebGoalsQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebOverviewQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    kind: Literal["WebOverviewQuery"] = "WebOverviewQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebOverviewQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebPageURLSearchQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    kind: Literal["WebPageURLSearchQuery"] = "WebPageURLSearchQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebPageURLSearchQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    searchTerm: str | None = None
    stripQueryParams: bool | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebStatsTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdownBy: WebStatsBreakdown
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeBounceRate: bool | None = None
    includeRevenue: bool | None = None
    includeScrollDepth: bool | None = None
    kind: Literal["WebStatsTableQuery"] = "WebStatsTableQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebStatsTableQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: str | None = Field(default=None, description="Executed ClickHouse query")
    columns: list | None = Field(default=None, description="Returned columns")
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: list[str] | None = Field(default=None, description="Query explanation output")
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = Field(default=None, description="Query metadata output")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query: str | None = Field(default=None, description="Input query string")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebTrendsItem]
    samplingRate: SamplingRate | None = None
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = Field(default=None, description="Types of returned columns")
    usedPreAggregatedTables: bool | None = None


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
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsPathBreakdownResult] = Field(..., max_length=1, min_length=1)
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class WebVitalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsItem]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ActionsNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: dict[str, Any] | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ActorsPropertyTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    groupTypeIndex: int | None = None
    kind: Literal["ActorsPropertyTaxonomyQuery"] = "ActorsPropertyTaxonomyQuery"
    maxPropertyValues: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[str]
    response: ActorsPropertyTaxonomyQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedHogQLQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    clickhouse: str | None = Field(default=None, description="Executed ClickHouse query")
    columns: list | None = Field(default=None, description="Returned columns")
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: list[str] | None = Field(default=None, description="Query explanation output")
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = Field(default=None, description="Query metadata output")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query: str | None = Field(default=None, description="Input query string")
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = Field(default=None, description="Types of returned columns")


class CachedInsightActorsQueryOptionsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[BreakdownItem] | None = None
    breakdowns: list[MultipleBreakdownOptions] | None = None
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    compare: list[CompareItem] | None = None
    day: list[DayItem] | None = None
    interval: list[IntervalItem] | None = None
    is_cached: bool
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    series: list[Series] | None = None
    status: list[StatusItem] | None = None
    timezone: str


class CachedRetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RetentionResult]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedWebTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    clickhouse: str | None = Field(default=None, description="Executed ClickHouse query")
    columns: list | None = Field(default=None, description="Returned columns")
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: list[str] | None = Field(default=None, description="Query explanation output")
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = Field(default=None, description="Query metadata output")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query: str | None = Field(default=None, description="Input query string")
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebTrendsItem]
    samplingRate: SamplingRate | None = None
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = Field(default=None, description="Types of returned columns")
    usedPreAggregatedTables: bool | None = None


class CachedWebVitalsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[WebVitalsItem]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    clickhouse: str | None = Field(default=None, description="Executed ClickHouse query")
    columns: list | None = Field(default=None, description="Returned columns")
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    explain: list[str] | None = Field(default=None, description="Query explanation output")
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    metadata: HogQLMetadataResponse | None = Field(default=None, description="Query metadata output")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query: str | None = Field(default=None, description="Input query string")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )
    types: list | None = Field(default=None, description="Types of returned columns")


class Response19(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingIssue]
    timings: list[QueryTiming] | None = Field(
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
    limit: int | None = None
    model: str
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    order_by: OrderBy
    order_direction: OrderDirection
    origin: EmbeddedDocument
    products: list[str]
    renderings: list[str]
    response: DocumentSimilarityQueryResponse | None = None
    tags: QueryLogTags | None = None
    threshold: float | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ErrorTrackingCorrelatedIssue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignee: ErrorTrackingIssueAssignee | None = None
    description: str | None = None
    event: str
    external_issues: list[ErrorTrackingExternalReference] | None = None
    first_seen: datetime
    id: str
    last_seen: datetime
    library: str | None = None
    name: str | None = None
    odds_ratio: float
    population: Population
    status: Status


class ErrorTrackingIssueCorrelationQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class ErrorTrackingSimilarIssuesQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange | None = None
    issueId: str
    kind: Literal["ErrorTrackingSimilarIssuesQuery"] = "ErrorTrackingSimilarIssuesQuery"
    limit: int | None = None
    maxDistance: float | None = None
    modelName: EmbeddingModelName | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    rendering: str | None = None
    response: ErrorTrackingSimilarIssuesQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class EventTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: int | None = None
    event: str | None = None
    kind: Literal["EventTaxonomyQuery"] = "EventTaxonomyQuery"
    maxPropertyValues: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[str] | None = None
    response: EventTaxonomyQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentExposureCriteria(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exposure_config: Union[ExperimentEventExposureConfig, ActionsNode] | None = None
    filterTestAccounts: bool | None = None
    multiple_variant_handling: MultipleVariantHandling | None = None


class ExperimentFunnelMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnel_order_type: StepOrderValue | None = None
    metric_type: Literal["funnel"] = "funnel"
    series: list[Union[EventsNode, ActionsNode]]


class ExperimentHoldoutType(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created_at: str | None = None
    created_by: UserBasicType | None = None
    description: str | None = None
    filters: list[FeatureFlagGroupType]
    id: float | None = None
    name: str
    updated_at: str | None = None


class ExperimentRatioMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    denominator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    fingerprint: str | None = None
    goal: ExperimentMetricGoal | None = None
    isSharedMetric: bool | None = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    metric_type: Literal["ratio"] = "ratio"
    name: str | None = None
    numerator: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    response: dict[str, Any] | None = None
    sharedMetricId: float | None = None
    uuid: str | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    binCount: int | None = None
    breakdownAttributionType: BreakdownAttributionType | None = BreakdownAttributionType.FIRST_TOUCH
    breakdownAttributionValue: int | None = None
    exclusions: list[Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]] | None = []
    funnelAggregateByHogQL: str | None = None
    funnelFromStep: int | None = None
    funnelOrderType: StepOrderValue | None = StepOrderValue.ORDERED
    funnelStepReference: FunnelStepReference | None = FunnelStepReference.TOTAL
    funnelToStep: int | None = Field(
        default=None, description="To select the range of steps for trends & time to convert funnels, 0-indexed"
    )
    funnelVizType: FunnelVizType | None = FunnelVizType.STEPS
    funnelWindowInterval: int | None = 14
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | None = FunnelConversionWindowTimeUnit.DAY
    goalLines: list[GoalLine] | None = Field(default=None, description="Goal Lines")
    hiddenLegendBreakdowns: list[str] | None = None
    layout: FunnelLayout | None = FunnelLayout.VERTICAL
    resultCustomizations: dict[str, ResultCustomizationByValue] | None = Field(
        default=None, description="Customizations for the appearance of result datasets."
    )
    showValuesOnSeries: bool | None = False
    useUdf: bool | None = None


class GroupsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int
    kind: Literal["GroupsQuery"] = "GroupsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    orderBy: list[str] | None = None
    properties: list[Union[GroupPropertyFilter, HogQLPropertyFilter]] | None = None
    response: GroupsQueryResponse | None = None
    search: str | None = None
    select: list[str] | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class HogQLASTQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    explain: bool | None = None
    filters: HogQLFilters | None = None
    kind: Literal["HogQLASTQuery"] = "HogQLASTQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    name: str | None = Field(default=None, description="Client provided name of the query")
    query: dict[str, Any]
    response: HogQLQueryResponse | None = None
    tags: QueryLogTags | None = None
    values: dict[str, Any] | None = Field(
        default=None, description="Constant values that can be referenced with the {placeholder} syntax in the query"
    )
    variables: dict[str, HogQLVariable] | None = Field(
        default=None, description="Variables to be substituted into the query"
    )
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class HogQLQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    explain: bool | None = None
    filters: HogQLFilters | None = None
    kind: Literal["HogQLQuery"] = "HogQLQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    name: str | None = Field(default=None, description="Client provided name of the query")
    query: str
    response: HogQLQueryResponse | None = None
    tags: QueryLogTags | None = None
    values: dict[str, Any] | None = Field(
        default=None, description="Constant values that can be referenced with the {placeholder} syntax in the query"
    )
    variables: dict[str, HogQLVariable] | None = Field(
        default=None, description="Variables to be substituted into the query"
    )
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightActorsQueryOptionsResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[BreakdownItem] | None = None
    breakdowns: list[MultipleBreakdownOptions] | None = None
    compare: list[CompareItem] | None = None
    day: list[DayItem] | None = None
    interval: list[IntervalItem] | None = None
    series: list[Series] | None = None
    status: list[StatusItem] | None = None


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
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    draftConversionGoal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3] | None = Field(
        default=None, description="Draft conversion goal that can be set in the UI without saving"
    )
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    integrationFilter: IntegrationFilter | None = Field(default=None, description="Filter by integration IDs")
    kind: Literal["MarketingAnalyticsAggregatedQuery"] = "MarketingAnalyticsAggregatedQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: MarketingAnalyticsAggregatedQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    select: list[str] | None = Field(
        default=None, description="Return a limited set of data. Will use default columns if empty."
    )
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class MarketingAnalyticsTableQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = Field(default=None, description="Compare to date range")
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    draftConversionGoal: Union[ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3] | None = Field(
        default=None, description="Draft conversion goal that can be set in the UI without saving"
    )
    filterTestAccounts: bool | None = Field(default=None, description="Filter test accounts")
    includeAllConversions: bool | None = Field(
        default=None, description="Include conversion goal rows even when they don't match campaign costs table"
    )
    includeRevenue: bool | None = None
    integrationFilter: IntegrationFilter | None = Field(default=None, description="Filter by integration type")
    kind: Literal["MarketingAnalyticsTableQuery"] = "MarketingAnalyticsTableQuery"
    limit: int | None = Field(default=None, description="Number of rows to return")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: list[list[Union[str, MarketingAnalyticsOrderByEnum]]] | None = Field(
        default=None, description="Columns to order by - similar to EventsQuery format"
    )
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: MarketingAnalyticsTableQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    select: list[str] | None = Field(
        default=None, description="Return a limited set of data. Will use default columns if empty."
    )
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    date_from: str | None = None
    date_to: str | None = None
    duration: list[RecordingDurationFilter]
    filter_group: MaxOuterUniversalFiltersGroup
    filter_test_accounts: bool | None = None
    order: RecordingOrder | None = RecordingOrder.START_TIME
    order_direction: RecordingOrderDirection | None = Field(
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
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class QueryResponseAlternative61(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RetentionResult]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class RecordingsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    kind: Literal["RecordingsQuery"] = "RecordingsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    operand: FilterLogicalOperator | None = FilterLogicalOperator.AND_
    order: RecordingOrder | None = RecordingOrder.START_TIME
    order_direction: RecordingOrderDirection | None = Field(
        default=RecordingOrderDirection.DESC,
        description=(
            "Replay originally had all ordering as descending by specifying the field name, this runs counter to Django"
            " behavior where the field name specifies ascending sorting (e.g. the_field_name) and -the_field_name would"
            " indicate descending order to avoid invalidating or migrating all existing filters we keep DESC as the"
            " default or allow specification of an explicit order direction here"
        ),
    )
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
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class RetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[RetentionResult]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class StickinessQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = Field(default=None, description="Compare to date range")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: IntervalType | None = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    intervalCount: int | None = Field(
        default=None, description="How many intervals comprise a period. Only used for cohorts, otherwise default 1."
    )
    kind: Literal["StickinessQuery"] = "StickinessQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: StickinessQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    stickinessFilter: StickinessFilter | None = Field(
        default=None, description="Properties specific to the stickiness insight"
    )
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class TeamTaxonomyQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["TeamTaxonomyQuery"] = "TeamTaxonomyQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: TeamTaxonomyQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class TrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    breakdownFilter: BreakdownFilter | None = Field(default=None, description="Breakdown of the events and actions")
    compareFilter: CompareFilter | None = Field(default=None, description="Compare to date range")
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = Field(
        default=None, description="Whether we should be comparing against a specific conversion goal"
    )
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: IntervalType | None = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["TrendsQuery"] = "TrendsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: TrendsQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    trendsFilter: TrendsFilter | None = Field(default=None, description="Properties specific to the trends insight")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class VectorSearchQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    embedding: list[float]
    embeddingVersion: float | None = None
    kind: Literal["VectorSearchQuery"] = "VectorSearchQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: VectorSearchQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    interval: IntervalType
    kind: Literal["WebTrendsQuery"] = "WebTrendsQuery"
    limit: int | None = None
    metrics: list[WebTrendsMetric]
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebTrendsQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class WebVitalsPathBreakdownQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    kind: Literal["WebVitalsPathBreakdownQuery"] = "WebVitalsPathBreakdownQuery"
    metric: WebVitalsMetric
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    percentile: WebVitalsPercentile
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebVitalsPathBreakdownQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    tags: QueryLogTags | None = None
    thresholds: list[float] = Field(..., max_length=2, min_length=2)
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class CachedErrorTrackingIssueCorrelationQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    is_cached: bool
    last_refresh: datetime
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    next_allowed_client_refresh: datetime
    offset: int | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timezone: str
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class CachedExperimentTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    count_query: TrendsQuery | None = None
    credible_intervals: dict[str, list[float]]
    exposure_query: TrendsQuery | None = None
    insight: list[dict[str, Any]]
    is_cached: bool
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    p_value: float
    probability: dict[str, float]
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    timezone: str
    variants: list[ExperimentVariantTrendsBaseStats]


class CalendarHeatmapQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    calendarHeatmapFilter: CalendarHeatmapFilter | None = Field(
        default=None, description="Properties specific to the trends insight"
    )
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = Field(
        default=None, description="Whether we should be comparing against a specific conversion goal"
    )
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: IntervalType | None = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["CalendarHeatmapQuery"] = "CalendarHeatmapQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: CalendarHeatmapResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class Response20(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    columns: list[str] | None = None
    error: str | None = Field(
        default=None,
        description="Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise.",
    )
    hasMore: bool | None = None
    hogql: str | None = Field(default=None, description="Generated HogQL query.")
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    resolved_date_range: ResolvedDateRangeResponse | None = Field(
        default=None, description="The date range used for the query"
    )
    results: list[ErrorTrackingCorrelatedIssue]
    timings: list[QueryTiming] | None = Field(
        default=None, description="Measured timings for different parts of the query generation process"
    )


class Response22(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: TrendsQuery | None = None
    credible_intervals: dict[str, list[float]]
    exposure_query: TrendsQuery | None = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantTrendsBaseStats]


class DataVisualizationNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    chartSettings: ChartSettings | None = None
    display: ChartDisplayType | None = None
    kind: Literal["DataVisualizationNode"] = "DataVisualizationNode"
    source: HogQLQuery
    tableSettings: TableSettings | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class DatabaseSchemaManagedViewTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    kind: DatabaseSchemaManagedViewTableKind
    name: str
    query: HogQLQuery
    row_count: float | None = None
    source_id: str | None = None
    type: Literal["managed_view"] = "managed_view"


class DatabaseSchemaMaterializedViewTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    last_run_at: str | None = None
    name: str
    query: HogQLQuery
    row_count: float | None = None
    status: str | None = None
    type: Literal["materialized_view"] = "materialized_view"


class DatabaseSchemaViewTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fields: dict[str, DatabaseSchemaField]
    id: str
    name: str
    query: HogQLQuery
    row_count: float | None = None
    type: Literal["view"] = "view"


class ErrorTrackingIssueCorrelationQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    events: list[str]
    kind: Literal["ErrorTrackingIssueCorrelationQuery"] = "ErrorTrackingIssueCorrelationQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: ErrorTrackingIssueCorrelationQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ErrorTrackingQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assignee: ErrorTrackingIssueAssignee | None = None
    dateRange: DateRange
    filterGroup: PropertyGroupFilter | None = None
    filterTestAccounts: bool | None = None
    issueId: str | None = None
    kind: Literal["ErrorTrackingQuery"] = "ErrorTrackingQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    orderBy: OrderBy1
    orderDirection: OrderDirection1 | None = None
    personId: str | None = None
    response: ErrorTrackingQueryResponse | None = None
    revenueEntity: RevenueEntity | None = None
    revenuePeriod: RevenuePeriod | None = None
    searchQuery: str | None = None
    status: Status2 | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")
    volumeResolution: int
    withAggregations: bool | None = None
    withFirstEvent: bool | None = None
    withLastEvent: bool | None = None


class ExperimentExposureQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    end_date: str | None = None
    experiment_id: int | None = None
    experiment_name: str
    exposure_criteria: ExperimentExposureCriteria | None = None
    feature_flag: dict[str, Any]
    holdout: ExperimentHoldoutType | None = None
    kind: Literal["ExperimentExposureQuery"] = "ExperimentExposureQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: ExperimentExposureQueryResponse | None = None
    start_date: str | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentFunnelMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    fingerprint: str | None = None
    funnel_order_type: StepOrderValue | None = None
    goal: ExperimentMetricGoal | None = None
    isSharedMetric: bool | None = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    metric_type: Literal["funnel"] = "funnel"
    name: str | None = None
    response: dict[str, Any] | None = None
    series: list[Union[EventsNode, ActionsNode]]
    sharedMetricId: float | None = None
    uuid: str | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentMeanMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_window: int | None = None
    conversion_window_unit: FunnelConversionWindowTimeUnit | None = None
    fingerprint: str | None = None
    goal: ExperimentMetricGoal | None = None
    ignore_zeros: bool | None = None
    isSharedMetric: bool | None = None
    kind: Literal["ExperimentMetric"] = "ExperimentMetric"
    lower_bound_percentile: float | None = None
    metric_type: Literal["mean"] = "mean"
    name: str | None = None
    response: dict[str, Any] | None = None
    sharedMetricId: float | None = None
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    upper_bound_percentile: float | None = None
    uuid: str | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentMeanMetricTypeProps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ignore_zeros: bool | None = None
    lower_bound_percentile: float | None = None
    metric_type: Literal["mean"] = "mean"
    source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]
    upper_bound_percentile: float | None = None


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


class ExperimentTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: TrendsQuery | None = None
    credible_intervals: dict[str, list[float]]
    exposure_query: TrendsQuery | None = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantTrendsBaseStats]


class FunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    breakdownFilter: BreakdownFilter | None = Field(default=None, description="Breakdown of the events and actions")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelsFilter: FunnelsFilter | None = Field(default=None, description="Properties specific to the funnels insight")
    interval: IntervalType | None = Field(
        default=None, description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`"
    )
    kind: Literal["FunnelsQuery"] = "FunnelsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: FunnelsQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseCalendarHeatmapResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: CalendarHeatmapResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: FunnelsQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseLifecycleQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: LifecycleQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBasePathsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: PathsQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseRetentionQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: RetentionQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightsQueryBaseTrendsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: NodeKind
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: TrendsQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    stats_version: int | None = None
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]


class LifecycleQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    interval: IntervalType | None = Field(
        default=IntervalType.DAY,
        description="Granularity of the response. Can be one of `hour`, `day`, `week` or `month`",
    )
    kind: Literal["LifecycleQuery"] = "LifecycleQuery"
    lifecycleFilter: LifecycleFilter | None = Field(
        default=None, description="Properties specific to the lifecycle insight"
    )
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: LifecycleQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    series: list[Union[EventsNode, ActionsNode, DataWarehouseNode]] = Field(
        ..., description="Events and actions to include"
    )
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class LogsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: DateRange
    filterGroup: PropertyGroupFilter
    kind: Literal["LogsQuery"] = "LogsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    orderBy: OrderBy3 | None = None
    response: LogsQueryResponse | None = None
    searchTerm: str | None = None
    serviceNames: list[str]
    severityLevels: list[LogSeverityLevel]
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class QueryResponseAlternative16(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: FunnelsQuery | None = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class QueryResponseAlternative17(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: TrendsQuery | None = None
    credible_intervals: dict[str, list[float]]
    exposure_query: TrendsQuery | None = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantTrendsBaseStats]


class QueryResponseAlternative18(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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


class QueryResponseAlternative56(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: FunnelsQuery | None = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class QueryResponseAlternative57(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: TrendsQuery | None = None
    credible_intervals: dict[str, list[float]]
    exposure_query: TrendsQuery | None = None
    insight: list[dict[str, Any]]
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    p_value: float
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantTrendsBaseStats]


class RetentionQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    breakdownFilter: BreakdownFilter | None = Field(default=None, description="Breakdown of the events and actions")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    kind: Literal["RetentionQuery"] = "RetentionQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
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
    ) = Field(default=[], description="Property filters for all series")
    response: RetentionQueryResponse | None = None
    retentionFilter: RetentionFilter = Field(..., description="Properties specific to the retention insight")
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class StickinessActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Compare | None = None
    day: Union[str, int] | None = None
    includeRecordings: bool | None = None
    kind: Literal["StickinessActorsQuery"] = "StickinessActorsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    operator: StickinessOperator | None = None
    response: ActorsQueryResponse | None = None
    series: int | None = None
    source: StickinessQuery
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class NamedArgs(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]


class IsExperimentFunnelMetric(BaseModel):
    namedArgs: NamedArgs | None = None


class IsExperimentMeanMetric(BaseModel):
    namedArgs: NamedArgs | None = None


class IsExperimentRatioMetric(BaseModel):
    namedArgs: NamedArgs | None = None


class CachedExperimentFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: FunnelsQuery | None = None
    insight: list[list[dict[str, Any]]]
    is_cached: bool
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    last_refresh: datetime
    next_allowed_client_refresh: datetime
    probability: dict[str, float]
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    timezone: str
    variants: list[ExperimentVariantFunnelsBaseStats]


class CachedExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    baseline: ExperimentStatsBaseValidated | None = None
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
        default=None, description="What triggered the calculation of the query, leave empty if user/immediate"
    )
    credible_intervals: dict[str, list[float]] | None = None
    insight: list[dict[str, Any]] | None = None
    is_cached: bool
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    last_refresh: datetime
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric] | None = None
    next_allowed_client_refresh: datetime
    p_value: float | None = None
    probability: dict[str, float] | None = None
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode | None = None
    significant: bool | None = None
    stats_version: int | None = None
    timezone: str
    variant_results: Union[list[ExperimentVariantResultFrequentist], list[ExperimentVariantResultBayesian]] | None = (
        None
    )
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]] | None = None


class CachedLegacyExperimentQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_key: str
    cache_target_age: datetime | None = None
    calculation_trigger: str | None = Field(
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
    query_metadata: dict[str, Any] | None = None
    query_status: QueryStatus | None = Field(
        default=None, description="Query status indicates whether next to the provided data, a query is still running."
    )
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    timezone: str
    variants: Union[list[ExperimentVariantTrendsBaseStats], list[ExperimentVariantFunnelsBaseStats]]


class Response21(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: FunnelsQuery | None = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class ExperimentFunnelsQueryResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    credible_intervals: dict[str, list[float]]
    expected_loss: float
    funnels_query: FunnelsQuery | None = None
    insight: list[list[dict[str, Any]]]
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    probability: dict[str, float]
    significance_code: ExperimentSignificanceCode
    significant: bool
    stats_version: int | None = None
    variants: list[ExperimentVariantFunnelsBaseStats]


class ExperimentMetricTimeseries(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    computed_at: str | None = None
    created_at: str
    errors: dict[str, str] | None = None
    experiment_id: float
    metric_uuid: str
    recalculation_created_at: str | None = None
    recalculation_status: str | None = None
    status: Status5
    timeseries: dict[str, ExperimentQueryResponse] | None = None
    updated_at: str


class ExperimentQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experiment_id: int | None = None
    kind: Literal["ExperimentQuery"] = "ExperimentQuery"
    metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    name: str | None = None
    response: ExperimentQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class ExperimentTrendsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    count_query: TrendsQuery
    experiment_id: int | None = None
    exposure_query: TrendsQuery | None = None
    fingerprint: str | None = None
    kind: Literal["ExperimentTrendsQuery"] = "ExperimentTrendsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    name: str | None = None
    response: ExperimentTrendsQueryResponse | None = None
    tags: QueryLogTags | None = None
    uuid: str | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class FunnelPathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelPathType: FunnelPathType | None = None
    funnelSource: FunnelsQuery
    funnelStep: int | None = None


class FunnelsActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelStep: int | None = Field(
        default=None,
        description=(
            "Index of the step for which we want to get the timestamp for, per person. Positive for converted persons,"
            " negative for dropped of persons."
        ),
    )
    funnelStepBreakdown: Union[int, str, float, list[Union[int, str, float]]] | None = Field(
        default=None,
        description=(
            "The breakdown value for which to get persons for. This is an array for person and event properties, a"
            " string for groups and an integer for cohorts."
        ),
    )
    funnelTrendsDropOff: bool | None = None
    funnelTrendsEntrancePeriodStart: str | None = Field(
        default=None,
        description="Used together with `funnelTrendsDropOff` for funnels time conversion date for the persons modal.",
    )
    includeRecordings: bool | None = None
    kind: Literal["FunnelsActorsQuery"] = "FunnelsActorsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: ActorsQueryResponse | None = None
    source: FunnelsQuery
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class PathsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_group_type_index: int | None = Field(default=None, description="Groups aggregation")
    dataColorTheme: float | None = Field(default=None, description="Colors used in the insight's visualization")
    dateRange: DateRange | None = Field(default=None, description="Date range for the query")
    filterTestAccounts: bool | None = Field(
        default=False, description="Exclude internal and test users by applying the respective filters"
    )
    funnelPathsFilter: FunnelPathsFilter | None = Field(
        default=None, description="Used for displaying paths in relation to funnel steps."
    )
    kind: Literal["PathsQuery"] = "PathsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    pathsFilter: PathsFilter = Field(..., description="Properties specific to the paths insight")
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
    ) = Field(default=[], description="Property filters for all series")
    response: PathsQueryResponse | None = None
    samplingFactor: float | None = Field(default=None, description="Sampling rate")
    tags: QueryLogTags | None = Field(default=None, description="Tags that will be added to the Query log comment")
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


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
    initiator: str | None = None
    plan: str | None = None
    query: str | None = ""


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
    id: str | None = None
    initiator: str | None = None
    parent_tool_call_id: str | None = None
    plan: str | None = None
    query: str | None = ""
    short_id: str | None = None
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
        ],
    ]


class ExperimentFunnelsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    experiment_id: int | None = None
    fingerprint: str | None = None
    funnels_query: FunnelsQuery
    kind: Literal["ExperimentFunnelsQuery"] = "ExperimentFunnelsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    name: str | None = None
    response: ExperimentFunnelsQueryResponse | None = None
    tags: QueryLogTags | None = None
    uuid: str | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class FunnelCorrelationQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelCorrelationEventExcludePropertyNames: list[str] | None = None
    funnelCorrelationEventNames: list[str] | None = None
    funnelCorrelationExcludeEventNames: list[str] | None = None
    funnelCorrelationExcludeNames: list[str] | None = None
    funnelCorrelationNames: list[str] | None = None
    funnelCorrelationType: FunnelCorrelationResultsType
    kind: Literal["FunnelCorrelationQuery"] = "FunnelCorrelationQuery"
    response: FunnelCorrelationResponse | None = None
    source: FunnelsActorsQuery
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightVizNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    embedded: bool | None = Field(default=None, description="Query is embedded inside another bordered component")
    full: bool | None = Field(default=None, description="Show with most visual options enabled. Used in insight scene.")
    hidePersonsModal: bool | None = None
    hideTooltipOnScroll: bool | None = None
    kind: Literal["InsightVizNode"] = "InsightVizNode"
    showCorrelationTable: bool | None = None
    showFilters: bool | None = None
    showHeader: bool | None = None
    showLastComputation: bool | None = None
    showLastComputationRefresh: bool | None = None
    showResults: bool | None = None
    showTable: bool | None = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    suppressSessionAnalysisWarning: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")
    vizSpecificOptions: VizSpecificOptions | None = None


class MultiVisualizationMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    commentary: str | None = None
    id: str | None = None
    parent_tool_call_id: str | None = None
    type: Literal["ai/multi_viz"] = "ai/multi_viz"
    visualizations: list[VisualizationItem]


class WebVitalsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: CompareFilter | None = None
    conversionGoal: Union[ActionConversionGoal, CustomEventConversionGoal] | None = None
    dateRange: DateRange | None = None
    doPathCleaning: bool | None = None
    filterTestAccounts: bool | None = None
    includeRevenue: bool | None = None
    kind: Literal["WebVitalsQuery"] = "WebVitalsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    orderBy: list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]] | None = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]
    response: WebGoalsQueryResponse | None = None
    sampling: WebAnalyticsSampling | None = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    tags: QueryLogTags | None = None
    useSessionsTable: bool | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class DatabaseSchemaQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["DatabaseSchemaQuery"] = "DatabaseSchemaQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: DatabaseSchemaQueryResponse | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class EndpointRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cache_age_seconds: float | None = None
    description: str | None = None
    is_active: bool | None = None
    name: str | None = None
    query: (
        Union[HogQLQuery, Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery]]
        | None
    ) = None


class FunnelCorrelationActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    kind: Literal["FunnelCorrelationActorsQuery"] = "FunnelCorrelationActorsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: ActorsQueryResponse | None = None
    source: FunnelCorrelationQuery
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Union[str, list[str], int] | None = None
    compare: Compare | None = None
    day: Union[str, int] | None = None
    includeRecordings: bool | None = None
    interval: int | None = Field(
        default=None, description="An interval selected out of available intervals in source query."
    )
    kind: Literal["InsightActorsQuery"] = "InsightActorsQuery"
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    response: ActorsQueryResponse | None = None
    series: int | None = None
    source: Union[TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery] = Field(
        ..., discriminator="kind"
    )
    status: str | None = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class InsightActorsQueryOptions(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["InsightActorsQueryOptions"] = "InsightActorsQueryOptions"
    response: InsightActorsQueryOptionsResponse | None = None
    source: Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery]
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class SessionBatchEventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: int | None = Field(default=None, description="Show events matching a given action")
    after: str | None = Field(default=None, description="Only fetch events that happened after this timestamp")
    before: str | None = Field(default=None, description="Only fetch events that happened before this timestamp")
    event: str | None = Field(default=None, description="Limit to events matching this string")
    filterTestAccounts: bool | None = Field(default=None, description="Filter test accounts")
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    group_by_session: bool | None = Field(
        default=None, description="Whether to group results by session_id in the response"
    )
    kind: Literal["SessionBatchEventsQuery"] = "SessionBatchEventsQuery"
    limit: int | None = Field(default=None, description="Number of rows to return")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: list[str] | None = Field(default=None, description="Columns to order by")
    personId: str | None = Field(default=None, description="Show events for a given person")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: SessionBatchEventsQueryResponse | None = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    session_ids: list[str] = Field(
        ..., description="List of session IDs to fetch events for. Will be translated to $session_id IN filter."
    )
    source: InsightActorsQuery | None = Field(default=None, description="source for querying events for insights")
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")
    where: list[str] | None = Field(default=None, description="HogQL filters to apply on returned data")


class ActorsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fixedProperties: (
        list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]] | None
    ) = Field(
        default=None,
        description=(
            "Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in"
            " actor_strategies.py."
        ),
    )
    kind: Literal["ActorsQuery"] = "ActorsQuery"
    limit: int | None = None
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = None
    orderBy: list[str] | None = None
    properties: (
        Union[
            list[Union[PersonPropertyFilter, CohortPropertyFilter, HogQLPropertyFilter, EmptyPropertyFilter]],
            PropertyGroupFilterValue,
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "Currently only person filters supported. No filters for querying groups. See `filter_conditions()` in"
            " actor_strategies.py."
        ),
    )
    response: ActorsQueryResponse | None = None
    search: str | None = None
    select: list[str] | None = None
    source: (
        Union[InsightActorsQuery, FunnelsActorsQuery, FunnelCorrelationActorsQuery, StickinessActorsQuery, HogQLQuery]
        | None
    ) = None
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class EventsQuery(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actionId: int | None = Field(default=None, description="Show events matching a given action")
    after: str | None = Field(default=None, description="Only fetch events that happened after this timestamp")
    before: str | None = Field(default=None, description="Only fetch events that happened before this timestamp")
    event: str | None = Field(default=None, description="Limit to events matching this string")
    filterTestAccounts: bool | None = Field(default=None, description="Filter test accounts")
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
    ) = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsQuery"] = "EventsQuery"
    limit: int | None = Field(default=None, description="Number of rows to return")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    offset: int | None = Field(default=None, description="Number of rows to skip before returning rows")
    orderBy: list[str] | None = Field(default=None, description="Columns to order by")
    personId: str | None = Field(default=None, description="Show events for a given person")
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
    ) = Field(default=None, description="Properties configurable in the interface")
    response: EventsQueryResponse | None = None
    select: list[str] = Field(..., description="Return a limited set of data. Required.")
    source: InsightActorsQuery | None = Field(default=None, description="source for querying events for insights")
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")
    where: list[str] | None = Field(default=None, description="HogQL filters to apply on returned data")


class HasPropertiesNode(RootModel[Union[EventsNode, EventsQuery, PersonsNode]]):
    root: Union[EventsNode, EventsQuery, PersonsNode]


class DataTableNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    allowSorting: bool | None = Field(
        default=None, description="Can the user click on column headers to sort the table? (default: true)"
    )
    columns: list[str] | None = Field(
        default=None, description="Columns shown in the table, unless the `source` provides them."
    )
    context: DataTableNodeViewPropsContext | None = Field(
        default=None, description="Context for the table, used by components like ColumnConfigurator"
    )
    defaultColumns: list[str] | None = Field(
        default=None, description="Default columns to use when resetting column configuration"
    )
    embedded: bool | None = Field(default=None, description="Uses the embedded version of LemonTable")
    expandable: bool | None = Field(default=None, description="Can expand row to show raw event data (default: true)")
    full: bool | None = Field(default=None, description="Show with most visual options enabled. Used in scenes.")
    hiddenColumns: list[str] | None = Field(
        default=None, description="Columns that aren't shown in the table, even if in columns or returned data"
    )
    kind: Literal["DataTableNode"] = "DataTableNode"
    pinnedColumns: list[str] | None = Field(
        default=None, description="Columns that are sticky when scrolling horizontally"
    )
    propertiesViaUrl: bool | None = Field(default=None, description="Link properties via the URL (default: false)")
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
            Response23,
        ]
        | None
    ) = None
    showActions: bool | None = Field(default=None, description="Show the kebab menu at the end of the row")
    showColumnConfigurator: bool | None = Field(
        default=None, description="Show a button to configure the table's columns if possible"
    )
    showDateRange: bool | None = Field(default=None, description="Show date range selector")
    showElapsedTime: bool | None = Field(default=None, description="Show the time it takes to run a query")
    showEventFilter: bool | None = Field(
        default=None, description="Include an event filter above the table (EventsNode only)"
    )
    showExport: bool | None = Field(default=None, description="Show the export button")
    showHogQLEditor: bool | None = Field(default=None, description="Include a HogQL query editor above HogQL tables")
    showOpenEditorButton: bool | None = Field(
        default=None, description="Show a button to open the current query as a new insight. (default: true)"
    )
    showPersistentColumnConfigurator: bool | None = Field(
        default=None, description="Show a button to configure and persist the table's default columns if possible"
    )
    showPropertyFilter: Union[bool, list[TaxonomicFilterGroupType]] | None = Field(
        default=None, description="Include a property filter above the table"
    )
    showReload: bool | None = Field(default=None, description="Show a reload button")
    showResultsTable: bool | None = Field(default=None, description="Show a results table")
    showSavedFilters: bool | None = Field(
        default=None, description="Show saved filters feature for this table (requires uniqueKey)"
    )
    showSavedQueries: bool | None = Field(default=None, description="Shows a list of saved queries")
    showSearch: bool | None = Field(default=None, description="Include a free text search field (PersonsNode only)")
    showTestAccountFilters: bool | None = Field(default=None, description="Show filter to exclude test accounts")
    showTimings: bool | None = Field(default=None, description="Show a detailed query timing breakdown")
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
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class HogQLAutocomplete(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    endPosition: int = Field(..., description="End position of the editor word")
    filters: HogQLFilters | None = Field(default=None, description="Table to validate the expression against")
    globals: dict[str, Any] | None = Field(default=None, description="Global values in scope")
    kind: Literal["HogQLAutocomplete"] = "HogQLAutocomplete"
    language: HogLanguage = Field(..., description="Language to validate")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query: str = Field(..., description="Query to validate")
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
        | None
    ) = Field(default=None, description="Query in whose context to validate.")
    startPosition: int = Field(..., description="Start position of the editor word")
    tags: QueryLogTags | None = None
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class HogQLMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    debug: bool | None = Field(default=None, description="Enable more verbose output, usually run from the /debug page")
    filters: HogQLFilters | None = Field(default=None, description="Extra filters applied to query via {filters}")
    globals: dict[str, Any] | None = Field(default=None, description="Extra globals for the query")
    kind: Literal["HogQLMetadata"] = "HogQLMetadata"
    language: HogLanguage = Field(..., description="Language to validate")
    modifiers: HogQLQueryModifiers | None = Field(default=None, description="Modifiers used when performing the query")
    query: str = Field(..., description="Query to validate")
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
        | None
    ) = Field(
        default=None,
        description='Query within which "expr" and "template" are validated. Defaults to "select * from events"',
    )
    tags: QueryLogTags | None = None
    variables: dict[str, HogQLVariable] | None = Field(
        default=None, description="Variables to be subsituted into the query"
    )
    version: float | None = Field(default=None, description="version of the node, used for schema migrations")


class HumanMessage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    content: str
    id: str | None = None
    parent_tool_call_id: str | None = None
    type: Literal["human"] = "human"
    ui_context: MaxUIContext | None = None


class MaxDashboardContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    filters: DashboardFilter
    id: float
    insights: list[MaxInsightContext]
    name: str | None = None
    type: Literal["dashboard"] = "dashboard"


class MaxInsightContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    filtersOverride: DashboardFilter | None = None
    id: str
    name: str | None = None
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
    variablesOverride: dict[str, HogQLVariable] | None = None


class MaxUIContext(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    actions: list[MaxActionContext] | None = None
    dashboards: list[MaxDashboardContext] | None = None
    events: list[MaxEventContext] | None = None
    insights: list[MaxInsightContext] | None = None


class QueryRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    async_: bool | None = Field(default=None, alias="async")
    client_query_id: str | None = Field(
        default=None, description="Client provided query ID. Can be used to retrieve the status or cancel the query."
    )
    filters_override: DashboardFilter | None = None
    name: str | None = Field(
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
    refresh: RefreshType | None = Field(
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
    variables_override: dict[str, dict[str, Any]] | None = None


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
    betaSource: bool | None = None
    caption: Union[str, Any] | None = None
    disabledReason: str | None = None
    docsUrl: str | None = None
    existingSource: bool | None = None
    featureFlag: str | None = None
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
    label: str | None = None
    name: ExternalDataSourceType
    unreleasedSource: bool | None = None


class Option(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    label: str
    value: str


class SourceFieldSelectConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    converter: SourceFieldSelectConfigConverter | None = None
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
    caption: str | None = None
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
