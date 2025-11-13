from enum import StrEnum
from typing import Literal

from semantic_version import Version

FROZEN_POSTHOG_VERSION = Version("1.43.0")  # Frozen at the last self-hosted version, just for backwards compat now
INTERNAL_BOT_EMAIL_SUFFIX = "@posthogbot.user"


# N.B. Keep this in sync with frontend enum (types.ts)
# AND ensure it is added to the Billing Service
class AvailableFeature(StrEnum):
    ZAPIER = "zapier"
    ORGANIZATIONS_PROJECTS = "organizations_projects"
    ENVIRONMENTS = "environments"
    SOCIAL_SSO = "social_sso"
    SAML = "saml"
    SCIM = "scim"
    SSO_ENFORCEMENT = "sso_enforcement"
    ADVANCED_PERMISSIONS = "advanced_permissions"  # TODO: Remove this once access_control is propagated
    ACCESS_CONTROL = "access_control"
    INGESTION_TAXONOMY = "ingestion_taxonomy"
    PATHS_ADVANCED = "paths_advanced"
    CORRELATION_ANALYSIS = "correlation_analysis"
    GROUP_ANALYTICS = "group_analytics"
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
    SURVEYS_RECURRING = "surveys_recurring"
    SURVEYS_MULTIPLE_QUESTIONS = "surveys_multiple_questions"
    AUTOMATIC_PROVISIONING = "automatic_provisioning"
    MANAGED_REVERSE_PROXY = "managed_reverse_proxy"
    DATA_PIPELINES = "data_pipelines"
    ALERTS = "alerts"
    DATA_COLOR_THEMES = "data_color_themes"
    API_QUERIES_CONCURRENCY = "api_queries_concurrency"
    ORGANIZATION_INVITE_SETTINGS = "organization_invite_settings"
    ORGANIZATION_SECURITY_SETTINGS = "organization_security_settings"
    ORGANIZATION_APP_QUERY_CONCURRENCY_LIMIT = "organization_app_query_concurrency_limit"
    SESSION_REPLAY_DATA_RETENTION = "session_replay_data_retention"
    AUDIT_LOGS = "audit_logs"


TREND_FILTER_TYPE_ACTIONS = "actions"
TREND_FILTER_TYPE_EVENTS = "events"
TREND_FILTER_TYPE_DATA_WAREHOUSE = "data_warehouse"

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
TRENDS_CALENDAR_HEATMAP = "CalendarHeatmap"

# Sync with frontend NON_TIME_SERIES_DISPLAY_TYPES
NON_TIME_SERIES_DISPLAY_TYPES = [
    TRENDS_TABLE,
    TRENDS_PIE,
    TRENDS_BAR_VALUE,
    TRENDS_WORLD_MAP,
    TRENDS_BOLD_NUMBER,
    TRENDS_CALENDAR_HEATMAP,
]
# Sync with frontend NON_BREAKDOWN_DISPLAY_TYPES
NON_BREAKDOWN_DISPLAY_TYPES = [TRENDS_BOLD_NUMBER, TRENDS_CALENDAR_HEATMAP]

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
    "CalendarHeatmap",
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
DATA_WAREHOUSE_ENTITIES = "data_warehouse_entities"
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
COMPARE_TO = "compare_to"
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
BREAKDOWN_HIDE_OTHER_AGGREGATION = "breakdown_hide_other_aggregation"
BREAKDOWN_NORMALIZE_URL = "breakdown_normalize_url"
SAMPLING_FACTOR = "sampling_factor"


BREAKDOWN_TYPES = Literal["event", "person", "cohort", "group", "session", "hogql"]


class FunnelOrderType(StrEnum):
    STRICT = "strict"
    UNORDERED = "unordered"
    ORDERED = "ordered"


class FunnelVizType(StrEnum):
    TRENDS = "trends"
    TIME_TO_CONVERT = "time_to_convert"
    STEPS = "steps"


class FunnelCorrelationType(StrEnum):
    EVENTS = "events"
    PROPERTIES = "properties"
    EVENT_WITH_PROPERTIES = "event_with_properties"


RETENTION_RECURRING = "retention_recurring"
RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS = "retention_first_time"
RETENTION_FIRST_EVER_OCCURRENCE = "retention_first_ever_occurrence"

DISTINCT_ID_FILTER = "distinct_id"
PERSON_UUID_FILTER = "person_uuid"


class AnalyticsDBMS(StrEnum):
    POSTGRES = "postgres"
    CLICKHOUSE = "clickhouse"


UNIQUE_USERS = "dau"
UNIQUE_GROUPS = "unique_group"
WEEKLY_ACTIVE = "weekly_active"
MONTHLY_ACTIVE = "monthly_active"


class ExperimentNoResultsErrorKeys(StrEnum):
    NO_EVENTS = "no-events"
    NO_FLAG_INFO = "no-flag-info"
    NO_CONTROL_VARIANT = "no-control-variant"
    NO_TEST_VARIANT = "no-test-variant"
    NO_RESULTS = "no-results"
    NO_EXPOSURES = "no-exposures"


class PropertyOperatorType(StrEnum):
    AND = "AND"
    OR = "OR"


class BreakdownAttributionType(StrEnum):
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


class EventDefinitionType(StrEnum):
    # Mimics EventDefinitionType in frontend/src/types.ts
    ALL = "all"
    ACTION_EVENT = "action_event"
    EVENT = "event"
    EVENT_POSTHOG = "event_posthog"
    EVENT_CUSTOM = "event_custom"


class FlagRequestType(StrEnum):
    DECIDE = "decide"
    LOCAL_EVALUATION = "local-evaluation"
    REMOTE_CONFIG = "remote-config"


SURVEY_TARGETING_FLAG_PREFIX = "survey-targeting-"
GENERATED_DASHBOARD_PREFIX = "Generated Dashboard"

ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER = "Feature Viewed"

PERMITTED_FORUM_DOMAINS = ["localhost", "posthog.com"]

INVITE_DAYS_VALIDITY = 3  # number of days for which team invites are valid

# Sync with frontend/src/scenes/surveys/constants.tsx
DEFAULT_SURVEY_APPEARANCE = {
    "fontFamily": "inherit",
    "backgroundColor": "#eeeded",
    "submitButtonColor": "black",
    "submitButtonTextColor": "white",
    "ratingButtonColor": "white",
    "ratingButtonActiveColor": "black",
    "borderColor": "#c9c6c6",
    "placeholder": "Start typing...",
    "whiteLabel": False,
    "displayThankYouMessage": True,
    "thankYouMessageHeader": "Thank you for your feedback!",
    "position": "bottom-right",
    "widgetType": "tab",
    "widgetLabel": "Feedback",
    "widgetColor": "black",
    "zIndex": "2147482647",
    "disabledButtonOpacity": "0.6",
    "maxWidth": "300px",
    "textSubtleColor": "#939393",
    "inputBackground": "white",
    "boxPadding": "20px 24px",
    "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.15)",
    "borderRadius": "10px",
    "shuffleQuestions": False,
    "surveyPopupDelaySeconds": None,
}

# Mapping of auth backend names to login method display names
AUTH_BACKEND_DISPLAY_NAMES = {
    "django.contrib.auth.backends.ModelBackend": "Email/password",
    "google-oauth2": "Google OAuth",
    "github": "GitHub",
    "gitlab": "GitLab",
    "saml": "SAML",
    "ee.api.authentication.CustomGoogleOAuth2": "Google OAuth",
    "ee.api.authentication.MultitenantSAMLAuth": "SAML",
}
