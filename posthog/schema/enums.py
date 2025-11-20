from __future__ import annotations

from enum import Enum, StrEnum


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


class AgentMode(StrEnum):
    PRODUCT_ANALYTICS = "product_analytics"
    SQL = "sql"
    SESSION_REPLAY = "session_replay"


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


class AssistantDateTimePropertyFilterOperator(StrEnum):
    IS_DATE_EXACT = "is_date_exact"
    IS_DATE_BEFORE = "is_date_before"
    IS_DATE_AFTER = "is_date_after"


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


class AssistantGenericPropertyFilterType(StrEnum):
    EVENT = "event"
    PERSON = "person"
    SESSION = "session"
    FEATURE = "feature"


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
    FILTER_ERROR_TRACKING_ISSUES = "filter_error_tracking_issues"
    FIND_ERROR_TRACKING_IMPACTFUL_ISSUE_EVENT_LIST = "find_error_tracking_impactful_issue_event_list"
    ERROR_TRACKING_EXPLAIN_ISSUE = "error_tracking_explain_issue"
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
    FILTER_WEB_ANALYTICS = "filter_web_analytics"
    CREATE_FEATURE_FLAG = "create_feature_flag"
    CREATE_EXPERIMENT = "create_experiment"
    EXECUTE_SQL = "execute_sql"
    SWITCH_MODE = "switch_mode"
    SUMMARIZE_SESSIONS = "summarize_sessions"
    CREATE_INSIGHT = "create_insight"


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


class Style(StrEnum):
    NONE = "none"
    NUMBER = "number"
    PERCENT = "percent"


class ColorMode(StrEnum):
    LIGHT = "light"
    DARK = "dark"


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


class DataWarehouseSyncInterval(StrEnum):
    FIELD_5MIN = "5min"
    FIELD_30MIN = "30min"
    FIELD_1HOUR = "1hour"
    FIELD_6HOUR = "6hour"
    FIELD_12HOUR = "12hour"
    FIELD_24HOUR = "24hour"
    FIELD_7DAY = "7day"
    FIELD_30DAY = "30day"


class DatabaseSchemaManagedViewTableKind(StrEnum):
    REVENUE_ANALYTICS_CHARGE = "revenue_analytics_charge"
    REVENUE_ANALYTICS_CUSTOMER = "revenue_analytics_customer"
    REVENUE_ANALYTICS_PRODUCT = "revenue_analytics_product"
    REVENUE_ANALYTICS_REVENUE_ITEM = "revenue_analytics_revenue_item"
    REVENUE_ANALYTICS_SUBSCRIPTION = "revenue_analytics_subscription"


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


class EmbeddingModelName(StrEnum):
    TEXT_EMBEDDING_3_SMALL_1536 = "text-embedding-3-small-1536"
    TEXT_EMBEDDING_3_LARGE_3072 = "text-embedding-3-large-3072"


class EntityType(StrEnum):
    ACTIONS = "actions"
    EVENTS = "events"
    DATA_WAREHOUSE = "data_warehouse"
    NEW_ENTITY = "new_entity"


class Status(StrEnum):
    ARCHIVED = "archived"
    ACTIVE = "active"
    RESOLVED = "resolved"
    PENDING_RELEASE = "pending_release"
    SUPPRESSED = "suppressed"


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


class CorrelationType(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class MultipleVariantHandling(StrEnum):
    EXCLUDE = "exclude"
    FIRST_SEEN = "first_seen"


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
    BING_ADS = "BingAds"
    SHOPIFY = "Shopify"


class ExternalQueryErrorCode(StrEnum):
    PLATFORM_ACCESS_REQUIRED = "platform_access_required"
    QUERY_EXECUTION_FAILED = "query_execution_failed"


class ExternalQueryStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class Tag(StrEnum):
    ALPHA = "alpha"
    BETA = "beta"


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
    SEARCH = "search"


class FilterLogicalOperator(StrEnum):
    AND_ = "AND"
    OR_ = "OR"


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


class FunnelVizType(StrEnum):
    STEPS = "steps"
    TIME_TO_CONVERT = "time_to_convert"
    TRENDS = "trends"


class Position(StrEnum):
    START = "start"
    END = "end"


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


class HogLanguage(StrEnum):
    HOG = "hog"
    HOG_JSON = "hogJson"
    HOG_QL = "hogQL"
    HOG_QL_EXPR = "hogQLExpr"
    HOG_TEMPLATE = "hogTemplate"
    LIQUID = "liquid"


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
    BING_ADS = "bing-ads"


class IntervalType(StrEnum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


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


class MaxBillingContextBillingPeriodInterval(StrEnum):
    MONTH = "month"
    YEAR = "year"


class MaxBillingContextSubscriptionLevel(StrEnum):
    FREE = "free"
    PAID = "paid"
    CUSTOM = "custom"


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
    SESSIONS_QUERY = "SessionsQuery"
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
    ERROR_TRACKING_BREAKDOWNS_QUERY = "ErrorTrackingBreakdownsQuery"
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


class PathType(StrEnum):
    FIELD_PAGEVIEW = "$pageview"
    FIELD_SCREEN = "$screen"
    CUSTOM_EVENT = "custom_event"
    HOGQL = "hogql"


class PlanningStepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


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


class QueryIndexUsage(StrEnum):
    UNDECISIVE = "undecisive"
    NO = "no"
    PARTIAL = "partial"
    YES = "yes"


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


class RefreshType(StrEnum):
    ASYNC_ = "async"
    ASYNC_EXCEPT_ON_CACHE_MISS = "async_except_on_cache_miss"
    BLOCKING = "blocking"
    FORCE_ASYNC = "force_async"
    FORCE_BLOCKING = "force_blocking"
    FORCE_CACHE = "force_cache"
    LAZY_ASYNC = "lazy_async"


class ResultCustomizationBy(StrEnum):
    VALUE = "value"
    POSITION = "position"


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


class MrrOrGross(StrEnum):
    MRR = "mrr"
    GROSS = "gross"


class RevenueAnalyticsOverviewItemKey(StrEnum):
    REVENUE = "revenue"
    PAYING_CUSTOMER_COUNT = "paying_customer_count"
    AVG_REVENUE_PER_CUSTOMER = "avg_revenue_per_customer"


class RevenueAnalyticsTopCustomersGroupBy(StrEnum):
    MONTH = "month"
    ALL = "all"


class SessionAttributionGroupBy(StrEnum):
    CHANNEL_TYPE = "ChannelType"
    MEDIUM = "Medium"
    SOURCE = "Source"
    CAMPAIGN = "Campaign"
    AD_IDS = "AdIds"
    REFERRING_DOMAIN = "ReferringDomain"
    INITIAL_URL = "InitialURL"


class SnapshotSource(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    UNKNOWN = "unknown"


class Storage(StrEnum):
    OBJECT_STORAGE_LTS = "object_storage_lts"
    OBJECT_STORAGE = "object_storage"


class SimpleIntervalType(StrEnum):
    DAY = "day"
    MONTH = "month"


class SourceFieldInputConfigType(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    SEARCH = "search"
    URL = "url"
    PASSWORD = "password"
    TIME = "time"
    NUMBER = "number"
    TEXTAREA = "textarea"


class SourceFieldSelectConfigConverter(StrEnum):
    STR_TO_INT = "str_to_int"
    STR_TO_BOOL = "str_to_bool"
    STR_TO_OPTIONAL_INT = "str_to_optional_int"


class StepOrderValue(StrEnum):
    STRICT = "strict"
    UNORDERED = "unordered"
    ORDERED = "ordered"


class StickinessComputationMode(StrEnum):
    NON_CUMULATIVE = "non_cumulative"
    CUMULATIVE = "cumulative"


class StickinessOperator(StrEnum):
    GTE = "gte"
    LTE = "lte"
    EXACT = "exact"


class SubscriptionDropoffMode(StrEnum):
    LAST_EVENT = "last_event"
    AFTER_DROPOFF_PERIOD = "after_dropoff_period"


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


class Display1(StrEnum):
    NUMBER = "number"
    EMOJI = "emoji"


class SurveyQuestionType(StrEnum):
    OPEN = "open"
    MULTIPLE_CHOICE = "multiple_choice"
    SINGLE_CHOICE = "single_choice"
    RATING = "rating"
    LINK = "link"


class SurveyTabPosition(StrEnum):
    TOP = "top"
    LEFT = "left"
    RIGHT = "right"
    BOTTOM = "bottom"


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


class DetailedResultsAggregationType(StrEnum):
    TOTAL = "total"
    AVERAGE = "average"
    MEDIAN = "median"


class UsageMetricDisplay(StrEnum):
    NUMBER = "number"
    SPARKLINE = "sparkline"


class UsageMetricFormat(StrEnum):
    NUMERIC = "numeric"
    CURRENCY = "currency"


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


class WebVitalsPercentile(StrEnum):
    P75 = "p75"
    P90 = "p90"
    P99 = "p99"


class Scale(StrEnum):
    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"
