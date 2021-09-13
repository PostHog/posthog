from enum import Enum


class AvailableFeature(str, Enum):
    ZAPIER = "zapier"
    ORGANIZATIONS_PROJECTS = "organizations_projects"
    GOOGLE_LOGIN = "google_login"
    SAML = "saml"
    DASHBOARD_COLLABORATION = "dashboard_collaboration"
    INGESTION_TAXONOMY = "ingestion_taxonomy"


TREND_FILTER_TYPE_ACTIONS = "actions"
TREND_FILTER_TYPE_EVENTS = "events"

SESSIONS_FILTER_RECORDING_TYPE = "recording"
SESSIONS_FILTER_COHORT_TYPE = "cohort"
SESSIONS_FILTER_PERSON_TYPE = "person"
SESSIONS_FILTER_ACTION_TYPE = "action_type"
SESSIONS_FILTER_EVENT_TYPE = "event_type"

TRENDS_CUMULATIVE = "ActionsLineGraphCumulative"
TRENDS_LINEAR = "ActionsLineGraph"
TRENDS_TABLE = "ActionsTable"
TRENDS_FUNNEL = "FunnelViz"
TRENDS_PIE = "ActionsPie"
TRENDS_RETENTION = "RetentionTable"
TRENDS_PATHS = "PathsViz"
TRENDS_BAR = "ActionsBar"
TRENDS_BAR_VALUE = "ActionsBarValue"

TRENDS_DISPLAY_BY_VALUE = [TRENDS_TABLE, TRENDS_PIE, TRENDS_BAR_VALUE]

# CONSTANTS
INSIGHT_TRENDS = "TRENDS"
INSIGHT_STICKINESS = "STICKINESS"
INSIGHT_LIFECYCLE = "LIFECYCLE"
INSIGHT_FUNNELS = "FUNNELS"
INSIGHT_PATHS = "PATHS"
INSIGHT_SESSIONS = "SESSIONS"
INSIGHT_RETENTION = "RETENTION"

INSIGHT_TO_DISPLAY = {
    INSIGHT_TRENDS: TRENDS_LINEAR,
    INSIGHT_STICKINESS: TRENDS_LINEAR,
    INSIGHT_LIFECYCLE: TRENDS_LINEAR,
    INSIGHT_FUNNELS: TRENDS_FUNNEL,
    INSIGHT_PATHS: TRENDS_PATHS,
    INSIGHT_SESSIONS: TRENDS_LINEAR,
    INSIGHT_RETENTION: TRENDS_RETENTION,
}


TRENDS_STICKINESS = "Stickiness"
TRENDS_LIFECYCLE = "Lifecycle"

SESSION_AVG = "avg"
SESSION_DIST = "dist"

SCREEN_EVENT = "$screen"
AUTOCAPTURE_EVENT = "$autocapture"
PAGEVIEW_EVENT = "$pageview"
CUSTOM_EVENT = "custom_event"


DATE_FROM = "date_from"
DATE_TO = "date_to"
ENTITIES = "entities"
ACTIONS = "actions"
EVENTS = "events"
EXCLUSIONS = "exclusions"
PROPERTIES = "properties"
SELECTOR = "selector"
INTERVAL = "interval"
DISPLAY = "display"
SHOWN_AS = "shown_as"
FILTER_TEST_ACCOUNTS = "filter_test_accounts"
BREAKDOWN_TYPE = "breakdown_type"
BREAKDOWN_VALUE = "breakdown_value"
COMPARE = "compare"
INSIGHT = "insight"
SESSION = "session"
BREAKDOWN = "breakdown"
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
FUNNEL_STEP_BREAKDOWN = "funnel_step_breakdown"
FUNNEL_LAYOUT = "layout"
FUNNEL_ORDER_TYPE = "funnel_order_type"
FUNNEL_VIZ_TYPE = "funnel_viz_type"
BIN_COUNT = "bin_count"
ENTRANCE_PERIOD_START = "entrance_period_start"
DROP_OFF = "drop_off"
FUNNEL_PATHS = "funnel_paths"
PATHS_INCLUDE_EVENT_TYPES = "include_event_types"
PATHS_INCLUDE_CUSTOM_EVENTS = "include_custom_events"
PATHS_EXCLUDE_EVENTS = "exclude_events"
FUNNEL_PATH_AFTER_STEP = "funneL_path_after_step"
FUNNEL_PATH_BEFORE_STEP = "funnel_path_before_step"
FUNNEL_PATH_BETWEEN_STEPS = "funneL_path_between_steps"


class FunnelOrderType(str, Enum):
    STRICT = "strict"
    UNORDERED = "unordered"
    ORDERED = "ordered"


class FunnelVizType(str, Enum):
    TRENDS = "trends"
    TIME_TO_CONVERT = "time_to_convert"
    STEPS = "steps"


RETENTION_RECURRING = "retention_recurring"
RETENTION_FIRST_TIME = "retention_first_time"

DISTINCT_ID_FILTER = "distinct_id"


class AnalyticsDBMS(str, Enum):
    POSTGRES = "postgres"
    CLICKHOUSE = "clickhouse"


WEEKLY_ACTIVE = "weekly_active"
MONTHLY_ACTIVE = "monthly_active"

ENVIRONMENT_TEST = "test"
ENVIRONMENT_PRODUCTION = "production"
