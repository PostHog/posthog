from enum import Enum
from typing import Literal

from semantic_version import Version

FROZEN_POSTHOG_VERSION = Version("1.43.0")  # Frozen at the last self-hosted version, just for backwards compat now
INTERNAL_BOT_EMAIL_SUFFIX = "@posthogbot.user"


# N.B. Keep this in sync with frontend enum (types.ts)
# AND ensure it is added to the Billing Service
class AvailableFeature(str, Enum):
    ZAPIER = "zapier"
    ORGANIZATIONS_PROJECTS = "organizations_projects"
    PROJECT_BASED_PERMISSIONING = "project_based_permissioning"
    SOCIAL_SSO = "social_sso"
    SAML = "saml"
    SSO_ENFORCEMENT = "sso_enforcement"
    DASHBOARD_COLLABORATION = "dashboard_collaboration"
    DASHBOARD_PERMISSIONING = "dashboard_permissioning"
    INGESTION_TAXONOMY = "ingestion_taxonomy"
    PATHS_ADVANCED = "paths_advanced"
    CORRELATION_ANALYSIS = "correlation_analysis"
    GROUP_ANALYTICS = "group_analytics"
    MULTIVARIATE_FLAGS = "multivariate_flags"
    EXPERIMENTATION = "experimentation"
    TAGGING = "tagging"
    BEHAVIORAL_COHORT_FILTERING = "behavioral_cohort_filtering"
    WHITE_LABELLING = "white_labelling"
    SUBSCRIPTIONS = "subscriptions"
    APP_METRICS = "app_metrics"
    RECORDINGS_PLAYLISTS = "recordings_playlists"
    ROLE_BASED_ACCESS = "role_based_access"
    RECORDINGS_FILE_EXPORT = "recordings_file_export"
    RECORDINGS_PERFORMANCE = "recordings_performance"
    SURVEYS_STYLING = "surveys_styling"
    SURVEYS_TEXT_HTML = "surveys_text_html"
    SURVEYS_MULTIPLE_QUESTIONS = "surveys_multiple_questions"


TREND_FILTER_TYPE_ACTIONS = "actions"
TREND_FILTER_TYPE_EVENTS = "events"

SESSION_RECORDINGS_FILTER_IDS = "session_ids"

TRENDS_CUMULATIVE = "ActionsLineGraphCumulative"
TRENDS_LINEAR = "ActionsLineGraph"
TRENDS_TABLE = "ActionsTable"
TRENDS_FUNNEL = "FunnelViz"
TRENDS_PIE = "ActionsPie"
TRENDS_PATHS = "PathsViz"
TRENDS_BAR = "ActionsBar"
TRENDS_BAR_VALUE = "ActionsBarValue"
TRENDS_WORLD_MAP = "WorldMap"
TRENDS_BOLD_NUMBER = "BoldNumber"

# Sync with frontend NON_TIME_SERIES_DISPLAY_TYPES
NON_TIME_SERIES_DISPLAY_TYPES = [
    TRENDS_TABLE,
    TRENDS_PIE,
    TRENDS_BAR_VALUE,
    TRENDS_WORLD_MAP,
    TRENDS_BOLD_NUMBER,
]
# Sync with frontend NON_BREAKDOWN_DISPLAY_TYPES
NON_BREAKDOWN_DISPLAY_TYPES = [TRENDS_BOLD_NUMBER]

# CONSTANTS
INSIGHT_TRENDS = "TRENDS"
INSIGHT_STICKINESS = "STICKINESS"
INSIGHT_LIFECYCLE = "LIFECYCLE"
INSIGHT_FUNNELS = "FUNNELS"
INSIGHT_PATHS = "PATHS"
INSIGHT_RETENTION = "RETENTION"

INSIGHT_TO_DISPLAY = {
    INSIGHT_TRENDS: TRENDS_LINEAR,
    INSIGHT_STICKINESS: TRENDS_LINEAR,
    INSIGHT_LIFECYCLE: TRENDS_LINEAR,
    INSIGHT_FUNNELS: TRENDS_FUNNEL,
    INSIGHT_PATHS: TRENDS_PATHS,
    INSIGHT_RETENTION: TRENDS_TABLE,
    # :KLUDGE: Sessions insight is no longer supported, but this is needed to make updating these insights possible.
    "SESSIONS": TRENDS_LINEAR,
}

DISPLAY_TYPES = Literal[
    "ActionsLineGraph",
    "ActionsLineGraphCumulative",
    "ActionsTable",
    "ActionsPie",
    "ActionsBar",
    "ActionsBarValue",
    "WorldMap",
    "BoldNumber",
]

DEPRECATED_DISPLAY_TYPES = Literal[
    "PathsViz",
    "FunnelViz",
]


TRENDS_STICKINESS = "Stickiness"
TRENDS_LIFECYCLE = "Lifecycle"

SCREEN_EVENT = "$screen"
AUTOCAPTURE_EVENT = "$autocapture"
PAGEVIEW_EVENT = "$pageview"
CUSTOM_EVENT = "custom_event"
HOGQL = "hogql"


DATE_FROM = "date_from"
DATE_TO = "date_to"
EXPLICIT_DATE = "explicit_date"
ENTITIES = "entities"
ACTIONS = "actions"
EVENTS = "events"
EXCLUSIONS = "exclusions"
PROPERTIES = "properties"
PROPERTY_GROUPS = "property_groups"
SELECTOR = "selector"
INTERVAL = "interval"
SMOOTHING_INTERVALS = "smoothing_intervals"
DISPLAY = "display"
SHOWN_AS = "shown_as"
CLIENT_QUERY_ID = "client_query_id"
FILTER_TEST_ACCOUNTS = "filter_test_accounts"
BREAKDOWN_TYPE = "breakdown_type"
BREAKDOWN_VALUE = "breakdown_value"
BREAKDOWN_GROUP_TYPE_INDEX = "breakdown_group_type_index"
COMPARE = "compare"
INSIGHT = "insight"
SESSION = "session"
BREAKDOWN = "breakdown"
BREAKDOWNS = "breakdowns"
BREAKDOWN_ATTRIBUTION_TYPE = "breakdown_attribution_type"
BREAKDOWN_ATTRIBUTION_VALUE = "breakdown_attribution_value"
BREAKDOWN_LIMIT = "breakdown_limit"
FROM_DASHBOARD = "from_dashboard"
PATH_TYPE = "path_type"
RETENTION_TYPE = "retention_type"
TOTAL_INTERVALS = "total_intervals"
SELECTED_INTERVAL = "selected_interval"
START_POINT = "start_point"
END_POINT = "end_point"
STEP_LIMIT = "step_limit"
TARGET_ENTITY = "target_entity"
RETURNING_ENTITY = "returning_entity"
OFFSET = "offset"
LIMIT = "limit"
PERIOD = "period"
STICKINESS_DAYS = "stickiness_days"
FORMULA = "formula"
ENTITY_ID = "entity_id"
ENTITY_TYPE = "entity_type"
ENTITY_MATH = "entity_math"
FUNNEL_WINDOW_DAYS = "funnel_window_days"
FUNNEL_WINDOW_INTERVAL_UNIT = "funnel_window_interval_unit"
FUNNEL_WINDOW_INTERVAL = "funnel_window_interval"
FUNNEL_FROM_STEP = "funnel_from_step"
FUNNEL_TO_STEP = "funnel_to_step"
FUNNEL_STEP = "funnel_step"
FUNNEL_CUSTOM_STEPS = "funnel_custom_steps"
FUNNEL_STEP_BREAKDOWN = "funnel_step_breakdown"
FUNNEL_LAYOUT = "layout"
FUNNEL_AGGREAGTE_BY_HOGQL = "funnel_aggregate_by_hogql"
FUNNEL_ORDER_TYPE = "funnel_order_type"
FUNNEL_VIZ_TYPE = "funnel_viz_type"
FUNNEL_CORRELATION_TYPE = "funnel_correlation_type"
FUNNEL_WINDOW_INTERVAL_TYPES = Literal["DAY", "SECOND", "MINUTE", "HOUR", "WEEK", "MONTH"]
# Funnel Correlation Properties
FUNNEL_CORRELATION_NAMES = "funnel_correlation_names"
FUNNEL_CORRELATION_EXCLUDE_NAMES = "funnel_correlation_exclude_names"
FUNNEL_CORRELATION_PROPERTY_VALUES = "funnel_correlation_property_values"
# Funnel Correlation Events
FUNNEL_CORRELATION_EVENT_NAMES = "funnel_correlation_event_names"
FUNNEL_CORRELATION_EXCLUDE_EVENT_NAMES = "funnel_correlation_exclude_event_names"
FUNNEL_CORRELATION_EVENT_EXCLUDE_PROPERTY_NAMES = "funnel_correlation_event_exclude_property_names"
FUNNEL_CORRELATION_PERSON_ENTITY = "funnel_correlation_person_entity"
FUNNEL_CORRELATION_PERSON_LIMIT = "funnel_correlation_person_limit"
FUNNEL_CORRELATION_PERSON_OFFSET = "funnel_correlation_person_offset"
FUNNEL_CORRELATION_PERSON_CONVERTED = "funnel_correlation_person_converted"
BIN_COUNT = "bin_count"
ENTRANCE_PERIOD_START = "entrance_period_start"
DROP_OFF = "drop_off"
FUNNEL_PATHS = "funnel_paths"
PATHS_HOGQL_EXPRESSION = "paths_hogql_expression"
PATHS_INCLUDE_EVENT_TYPES = "include_event_types"
PATHS_INCLUDE_CUSTOM_EVENTS = "include_custom_events"
PATHS_EXCLUDE_EVENTS = "exclude_events"
FUNNEL_PATH_AFTER_STEP = "funnel_path_after_step"
FUNNEL_PATH_BEFORE_STEP = "funnel_path_before_step"
FUNNEL_PATH_BETWEEN_STEPS = "funnel_path_between_steps"
PATH_GROUPINGS = "path_groupings"
PATH_REPLACEMENTS = "path_replacements"
LOCAL_PATH_CLEANING_FILTERS = "local_path_cleaning_filters"
PATH_START_KEY = "path_start_key"
PATH_END_KEY = "path_end_key"
PATH_DROPOFF_KEY = "path_dropoff_key"
PATH_EDGE_LIMIT = "edge_limit"
PATH_MIN_EDGE_WEIGHT = "min_edge_weight"
PATH_MAX_EDGE_WEIGHT = "max_edge_weight"
AGGREGATION_GROUP_TYPE_INDEX = "aggregation_group_type_index"
BREAKDOWN_HISTOGRAM_BIN_COUNT = "breakdown_histogram_bin_count"
BREAKDOWN_NORMALIZE_URL = "breakdown_normalize_url"
SAMPLING_FACTOR = "sampling_factor"


BREAKDOWN_TYPES = Literal["event", "person", "cohort", "group", "session", "hogql"]


class FunnelOrderType(str, Enum):
    STRICT = "strict"
    UNORDERED = "unordered"
    ORDERED = "ordered"


class FunnelVizType(str, Enum):
    TRENDS = "trends"
    TIME_TO_CONVERT = "time_to_convert"
    STEPS = "steps"


class FunnelCorrelationType(str, Enum):
    EVENTS = "events"
    PROPERTIES = "properties"
    EVENT_WITH_PROPERTIES = "event_with_properties"


RETENTION_RECURRING = "retention_recurring"
RETENTION_FIRST_TIME = "retention_first_time"

DISTINCT_ID_FILTER = "distinct_id"
PERSON_UUID_FILTER = "person_uuid"


class AnalyticsDBMS(str, Enum):
    POSTGRES = "postgres"
    CLICKHOUSE = "clickhouse"


UNIQUE_USERS = "dau"
UNIQUE_GROUPS = "unique_group"
WEEKLY_ACTIVE = "weekly_active"
MONTHLY_ACTIVE = "monthly_active"


class RetentionQueryType(str, Enum):
    RETURNING = "returning"
    TARGET = "target"
    TARGET_FIRST_TIME = "target_first_time"


class ExperimentSignificanceCode(str, Enum):
    SIGNIFICANT = "significant"
    NOT_ENOUGH_EXPOSURE = "not_enough_exposure"
    LOW_WIN_PROBABILITY = "low_win_probability"
    HIGH_LOSS = "high_loss"
    HIGH_P_VALUE = "high_p_value"


class PropertyOperatorType(str, Enum):
    AND = "AND"
    OR = "OR"


class BreakdownAttributionType(str, Enum):
    FIRST_TOUCH = "first_touch"
    # FIRST_TOUCH attribution means the breakdown value is the first property value found within all funnel steps
    LAST_TOUCH = "last_touch"
    # LAST_TOUCH attribution means the breakdown value is the last property value found within all funnel steps
    STEP = "step"
    # STEP attribution means the breakdown value is the X'th step property value found within the funnel.
    # where X is the `breakdown_attribution_value`
    ALL_EVENTS = "all_events"
    # ALL_EVENTS attribution means the breakdown value is valid only when it exists on all funnel steps


MAX_SLUG_LENGTH = 48
GROUP_TYPES_LIMIT = 5
BREAKDOWN_VALUES_LIMIT = 25
BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES = 300
CSV_EXPORT_LIMIT = 10000


class EventDefinitionType(str, Enum):
    # Mimics EventDefinitionType in frontend/src/types.ts
    ALL = "all"
    ACTION_EVENT = "action_event"
    EVENT = "event"
    EVENT_POSTHOG = "event_posthog"
    EVENT_CUSTOM = "event_custom"


class FlagRequestType(str, Enum):
    DECIDE = "decide"
    LOCAL_EVALUATION = "local-evaluation"


ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER = "Feature Viewed"
DATA_WAREHOUSE_TASK_QUEUE = "data-warehouse-task-queue"
BATCH_EXPORTS_TASK_QUEUE = "no-sandbox-python-django"
