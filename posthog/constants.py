from enum import Enum

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
TRENDS_TABLE = "ActionsTable"
TRENDS_RETENTION = "RetentionTable"
TRENDS_PATHS = "PathsViz"

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
PROPERTIES = "properties"
SELECTOR = "selector"
INTERVAL = "interval"
DISPLAY = "display"
SHOWN_AS = "shown_as"
BREAKDOWN_TYPE = "breakdown_type"
BREAKDOWN_VALUE = "breakdown_value"
COMPARE = "compare"
INSIGHT = "insight"
SESSION = "session"
BREAKDOWN = "breakdown"
FROM_DASHBOARD = "from_dashboard"
PATH_TYPE = "path_type"
RETENTION_TYPE = "retention_type"
TOTAL_INTERVALS = "total_intervals"
SELECTED_INTERVAL = "selected_interval"
START_POINT = "start_point"
TARGET_ENTITY = "target_entity"
RETURNING_ENTITY = "returning_entity"
OFFSET = "offset"
PERIOD = "period"
STICKINESS_DAYS = "stickiness_days"

RETENTION_RECURRING = "retention_recurring"
RETENTION_FIRST_TIME = "retention_first_time"

DISTINCT_ID_FILTER = "distinct_id"


class RDBMS(str, Enum):
    POSTGRES = "postgres"
    CLICKHOUSE = "clickhouse"
