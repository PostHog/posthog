import { LemonSelectOptions } from '@posthog/lemon-ui'

import { ChartDisplayCategory, ChartDisplayType, Region, SSOProvider } from '../types'

// Sync with backend DISPLAY_TYPES_TO_CATEGORIES
export const DISPLAY_TYPES_TO_CATEGORIES: Record<ChartDisplayType, ChartDisplayCategory> = {
    [ChartDisplayType.ActionsLineGraph]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsBar]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsStackedBar]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsAreaGraph]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsLineGraphCumulative]: ChartDisplayCategory.CumulativeTimeSeries,
    [ChartDisplayType.BoldNumber]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsPie]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsBarValue]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsTable]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.WorldMap]: ChartDisplayCategory.TotalValue,
}
export const NON_TIME_SERIES_DISPLAY_TYPES = Object.entries(DISPLAY_TYPES_TO_CATEGORIES)
    .filter(([, category]) => category === ChartDisplayCategory.TotalValue)
    .map(([displayType]) => displayType as ChartDisplayType)

/** Display types for which `breakdown` is hidden and ignored. Sync with backend NON_BREAKDOWN_DISPLAY_TYPES. */
export const NON_BREAKDOWN_DISPLAY_TYPES = [ChartDisplayType.BoldNumber]
/** Display types which only work with a single series. */
export const SINGLE_SERIES_DISPLAY_TYPES = [ChartDisplayType.WorldMap, ChartDisplayType.BoldNumber]

export const NON_VALUES_ON_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.ActionsTable,
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
]

/** Display types for which a percent stack view is available. */
export const PERCENT_STACK_VIEW_DISPLAY_TYPE = [
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsPie,
]

export enum OrganizationMembershipLevel {
    Member = 1,
    Admin = 8,
    Owner = 15,
}

export enum TeamMembershipLevel {
    Member = 1,
    Admin = 8,
}

export type EitherMembershipLevel = OrganizationMembershipLevel | TeamMembershipLevel

/** See posthog/api/organization.py for details. */
export enum PluginsAccessLevel {
    None = 0,
    Config = 3,
    Install = 6,
    Root = 9,
}

/** Collaboration restriction level (which is a dashboard setting). Sync with DashboardPrivilegeLevel. */
export enum DashboardRestrictionLevel {
    EveryoneInProjectCanEdit = 21,
    OnlyCollaboratorsCanEdit = 37,
}

/** Collaboration privilege level (which is a user property). Sync with DashboardRestrictionLevel. */
export enum DashboardPrivilegeLevel {
    CanView = 21,
    CanEdit = 37,
    /** This is not a value that can be set in the DB – it's inferred. */
    _ProjectAdmin = 888,
    /** This is not a value that can be set in the DB – it's inferred. */
    _Owner = 999,
}

export const privilegeLevelToName: Record<DashboardPrivilegeLevel, string> = {
    [DashboardPrivilegeLevel.CanView]: 'can view',
    [DashboardPrivilegeLevel.CanEdit]: 'can edit',
    [DashboardPrivilegeLevel._Owner]: 'owner',
    [DashboardPrivilegeLevel._ProjectAdmin]: 'can edit',
}

// Persons
export const PERSON_DISTINCT_ID_MAX_SIZE = 3
export const PERSON_DISPLAY_NAME_COLUMN_NAME = 'person_display_name -- Person '

// Sync with .../api/person.py and .../ingestion/hooks.ts
export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    'email',
    'Email',
    'name',
    'Name',
    'username',
    'Username',
    'UserName',
]

// Feature Flags & Experiments
export const INSTANTLY_AVAILABLE_PROPERTIES = [
    '$geoip_city_name',
    '$geoip_country_name',
    '$geoip_country_code',
    '$geoip_continent_name',
    '$geoip_continent_code',
    '$geoip_postal_code',
    '$geoip_time_zone',
    // Person and group identifiers
    '$group_key',
    'distinct_id',
]
export const MAX_EXPERIMENT_VARIANTS = 20
export const EXPERIMENT_DEFAULT_DURATION = 14 // days

// Event constants
export const ACTION_TYPE = 'action_type'
export const EVENT_TYPE = 'event_type'
export const STALE_EVENT_SECONDS = 30 * 24 * 60 * 60 // 30 days

/** @deprecated: should be removed once backend is updated */
export enum ShownAsValue {
    VOLUME = 'Volume',
    STICKINESS = 'Stickiness',
    LIFECYCLE = 'Lifecycle',
}

// Retention constants
export const RETENTION_RECURRING = 'retention_recurring'
export const RETENTION_FIRST_TIME = 'retention_first_time'

export const WEBHOOK_SERVICES: Record<string, string> = {
    Slack: 'slack.com',
    Discord: 'discord.com',
    Teams: 'office.com',
}

// NOTE: Run `DEBUG=1 python manage.py sync_feature_flags` locally to sync these flags into your local project
// By default all flags are boolean but you can add `multivariate` to the comment to have it created as multivariate with "test" and "control" values

export const FEATURE_FLAGS = {
    // Experiments / beta features
    FUNNELS_CUE_OPT_OUT: 'funnels-cue-opt-out-7301', // owner: @neilkakkar
    HISTORICAL_EXPORTS_V2: 'historical-exports-v2', // owner @macobo
    INGESTION_WARNINGS_ENABLED: 'ingestion-warnings-enabled', // owner: @tiina303
    SESSION_RESET_ON_LOAD: 'session-reset-on-load', // owner: @benjackwhite
    DEBUG_REACT_RENDERS: 'debug-react-renders', // owner: @benjackwhite
    AUTO_ROLLBACK_FEATURE_FLAGS: 'auto-rollback-feature-flags', // owner: @EDsCODE
    ONBOARDING_V2_DEMO: 'onboarding-v2-demo', // owner: #team-growth
    QUERY_RUNNING_TIME: 'query_running_time', // owner: @mariusandra
    QUERY_TIMINGS: 'query-timings', // owner: @mariusandra
    HEDGEHOG_MODE: 'hedgehog-mode', // owner: @benjackwhite
    HEDGEHOG_MODE_DEBUG: 'hedgehog-mode-debug', // owner: @benjackwhite
    HIGH_FREQUENCY_BATCH_EXPORTS: 'high-frequency-batch-exports', // owner: @tomasfarias
    PERSON_BATCH_EXPORTS: 'person-batch-exports', // owner: @tomasfarias
    SESSIONS_BATCH_EXPORTS: 'sessions-batch-exports', // owner: @tomasfarias
    FF_DASHBOARD_TEMPLATES: 'ff-dashboard-templates', // owner: @EDsCODE
    ARTIFICIAL_HOG: 'artificial-hog', // owner: @Twixes
    PRODUCT_SPECIFIC_ONBOARDING: 'product-specific-onboarding', // owner: @raquelmsmith
    REDIRECT_SIGNUPS_TO_INSTANCE: 'redirect-signups-to-instance', // owner: @raquelmsmith
    APPS_AND_EXPORTS_UI: 'apps-and-exports-ui', // owner: @benjackwhite
    HOGQL_DASHBOARD_ASYNC: 'hogql-dashboard-async', // owner: @webjunkie
    WEBHOOKS_DENYLIST: 'webhooks-denylist', // owner: #team-pipeline
    PIPELINE_UI: 'pipeline-ui', // owner: #team-pipeline
    PERSON_FEED_CANVAS: 'person-feed-canvas', // owner: #project-canvas
    FEATURE_FLAG_COHORT_CREATION: 'feature-flag-cohort-creation', // owner: @neilkakkar #team-feature-success
    INSIGHT_HORIZONTAL_CONTROLS: 'insight-horizontal-controls', // owner: @benjackwhite
    SURVEYS_ADAPTIVE_LIMITS: 'surveys-adaptive-limits', // owner: #team-surveys
    SURVEYS_ACTIONS: 'surveys-actions', // owner: #team-surveys
    SURVEYS_CUSTOM_FONTS: 'surveys-custom-fonts', // owner: #team-surveys
    SURVEYS_PARTIAL_RESPONSES: 'surveys-partial-responses', // owner: #team-surveys
    SURVEYS_NEW_QUESTION_VIZ: 'surveys-new-question-viz', // owner: #team-surveys
    DISCUSSIONS: 'discussions', // owner: @daibhin @benjackwhite
    REDIRECT_INSIGHT_CREATION_PRODUCT_ANALYTICS_ONBOARDING: 'redirect-insight-creation-product-analytics-onboarding', // owner: @biancayang
    AI_SESSION_SUMMARY: 'ai-session-summary', // owner: #team-replay
    AI_SESSION_PERMISSIONS: 'ai-session-permissions', // owner: #team-replay
    SESSION_REPLAY_DOCTOR: 'session-replay-doctor', // owner: #team-replay
    AUDIT_LOGS_ACCESS: 'audit-logs-access', // owner: #team-growth
    SUBSCRIBE_FROM_PAYGATE: 'subscribe-from-paygate', // owner: #team-growth
    HEATMAPS_UI: 'heatmaps-ui', // owner: @benjackwhite
    THEME: 'theme', // owner: @aprilfools
    PROXY_AS_A_SERVICE: 'proxy-as-a-service', // owner: #team-infrastructure
    SETTINGS_PERSONS_JOIN_MODE: 'settings-persons-join-mode', // owner: @robbie-c
    SETTINGS_PERSONS_ON_EVENTS_HIDDEN: 'settings-persons-on-events-hidden', // owner: @Twixes
    HOG: 'hog', // owner: @mariusandra
    PERSONLESS_EVENTS_NOT_SUPPORTED: 'personless-events-not-supported', // owner: @raquelmsmith
    SETTINGS_BOUNCE_RATE_PAGE_VIEW_MODE: 'settings-bounce-rate-page-view-mode', // owner: @robbie-c
    ONBOARDING_DASHBOARD_TEMPLATES: 'onboarding-dashboard-templates', // owner: @raquelmsmith
    SETTINGS_SESSION_TABLE_VERSION: 'settings-session-table-version', // owner: @robbie-c
    INSIGHT_FUNNELS_USE_UDF: 'insight-funnels-use-udf', // owner: @aspicer #team-product-analytics
    INSIGHT_FUNNELS_USE_UDF_TRENDS: 'insight-funnels-use-udf-trends', // owner: @aspicer #team-product-analytics
    INSIGHT_FUNNELS_USE_UDF_TIME_TO_CONVERT: 'insight-funnels-use-udf-time-to-convert', // owner: @aspicer #team-product-analytics
    BATCH_EXPORTS_POSTHOG_HTTP: 'posthog-http-batch-exports',
    HEDGEHOG_SKIN_SPIDERHOG: 'hedgehog-skin-spiderhog', // owner: @benjackwhite
    WEB_EXPERIMENTS: 'web-experiments', // owner: @team-feature-success
    ENVIRONMENTS: 'environments', // owner: @Twixes #team-product-analytics
    REPLAY_TEMPLATES: 'replay-templates', // owner: @raquelmsmith #team-replay
    EXPERIMENTS_HOGQL: 'experiments-hogql', // owner: @jurajmajerik #team-experiments
    MESSAGING: 'messaging', // owner @haven #team-messaging
    MESSAGING_EARLY_ACCESS: 'messaging-product', // owner @haven #team-messaging
    ENVIRONMENTS_ROLLBACK: 'environments-rollback', // owner: @yasen #team-platform
    AI_SURVEY_RESPONSE_SUMMARY: 'ai-survey-response-summary', // owner: #team-surveys
    SELF_SERVE_CREDIT_OVERRIDE: 'self-serve-credit-override', // owner: @zach
    CUSTOM_CSS_THEMES: 'custom-css-themes', // owner: @daibhin
    METALYTICS: 'metalytics', // owner: @surbhi
    REMOTE_CONFIG: 'remote-config', // owner: @benjackwhite
    SITE_DESTINATIONS: 'site-destinations', // owner: @mariusandra #team-cdp
    SITE_APP_FUNCTIONS: 'site-app-functions', // owner: @mariusandra #team-cdp
    INSIGHT_ALERTS_CDP: 'insight-alerts-cdp', // owner: @anirudhpillai #team-product-analytics
    HOG_TRANSFORMATIONS_CUSTOM_HOG_ENABLED: 'hog-transformation-custom-hog-code', // owner: #team-cdp
    REPLAY_HOGQL_FILTERS: 'replay-hogql-filters', // owner: @pauldambra #team-replay
    REPLAY_GROUPS_FILTERS: 'replay-groups-filters', // owner: @pauldambra #team-replay
    SUPPORT_MESSAGE_OVERRIDE: 'support-message-override', // owner: @abigail
    BILLING_SKIP_FORECASTING: 'billing-skip-forecasting', // owner: @zach
    CDP_ACTIVITY_LOG_NOTIFICATIONS: 'cdp-activity-log-notifications', // owner: #team-cdp
    COOKIELESS_SERVER_HASH_MODE_SETTING: 'cookieless-server-hash-mode-setting', // owner: @robbie-c #team-web-analytics
    INSIGHT_COLORS: 'insight-colors', // owner: @thmsobrmlr #team-product-analytics
    WEB_ANALYTICS_FOR_MOBILE: 'web-analytics-for-mobile', // owner: @robbie-c #team-web-analytics
    LLM_OBSERVABILITY: 'llm-observability', // owner: #team-ai-product-manager
    ONBOARDING_SESSION_REPLAY_SEPARATE_STEP: 'onboarding-session-replay-separate-step', // owner: @joshsny #team-growth
    EXPERIMENT_INTERVAL_TIMESERIES: 'experiments-interval-timeseries', // owner: @jurajmajerik #team-experiments
    EXPERIMENT_P_VALUE: 'experiment-p-value', // owner: @jurajmajerik #team-experiments
    WEB_ANALYTICS_IMPROVED_PATH_CLEANING: 'web-analytics-improved-path-cleaning', // owner: @rafaeelaudibert #team-web-analytics
    EXPERIMENTAL_DASHBOARD_ITEM_RENDERING: 'experimental-dashboard-item-rendering', // owner: @thmsobrmlr #team-product-analytics
    RECORDINGS_AI_FILTER: 'recordings-ai-filter', // owner: @veryayskiy #team-replay
    PATHS_V2: 'paths-v2', // owner: @thmsobrmlr #team-product-analytics
    EXPERIMENTS_NEW_QUERY_RUNNER: 'experiments-new-query-runner', // owner: #team-experiments
    RECORDINGS_AI_REGEX: 'recordings-ai-regex', // owner: @veryayskiy #team-replay
    EXPERIMENTS_NEW_QUERY_RUNNER_AA_TEST: 'experiments-new-query-runner-aa-test', // #team-experiments
    ONBOARDING_DATA_WAREHOUSE_FOR_PRODUCT_ANALYTICS: 'onboarding-data-warehouse-for-product-analytics', // owner: @joshsny #team-growth
    DELAYED_LOADING_ANIMATION: 'delayed-loading-animation', // owner: @raquelmsmith
    SESSION_RECORDINGS_PLAYLIST_COUNT_COLUMN: 'session-recordings-playlist-count-column', // owner: @pauldambra #team-replay
    WEB_ANALYTICS_PAGE_REPORTS: 'web-analytics-page-reports', // owner: @lricoy #team-web-analytics
    REVENUE_ANALYTICS: 'revenue-analytics-beta', // owner: @rafaeelaudibert #team-revenue-analytics
    REVENUE_ANALYTICS_PRODUCT_GROUPING: 'revenue-analytics-product-grouping', // owner: @rafaeelaudibert #team-revenue-analytics
    REVENUE_ANALYTICS_COHORT_GROUPING: 'revenue-analytics-cohort-grouping', // owner: @rafaeelaudibert #team-revenue-analytics
    REVENUE_ANALYTICS_COUNTRY_GROUPING: 'revenue-analytics-country-grouping', // owner: @rafaeelaudibert #team-revenue-analytics
    SUPPORT_FORM_IN_ONBOARDING: 'support-form-in-onboarding', // owner: @joshsny #team-growth
    AI_SETUP_WIZARD: 'ai-setup-wizard', // owner: @joshsny #team-growth
    CRM_BLOCKING_QUERIES: 'crm-blocking-queries', // owner: @danielbachhuber #team-crm
    CRM_ITERATION_ONE: 'crm-iteration-one', // owner: @danielbachhuber #team-crm
    RECORDINGS_SIMILAR_RECORDINGS: 'recordings-similar-recordings', // owner: @veryayskiy #team-replay
    RECORDINGS_BLOBBY_V2_REPLAY: 'recordings-blobby-v2-replay', // owner: @pl #team-cdp
    SETTINGS_SESSIONS_V2_JOIN: 'settings-sessions-v2-join', // owner: @robbie-c #team-web-analytics
    SAVE_INSIGHT_TASK: 'save-insight-task', // owner: @joshsny #team-growth
    DASHBOARD_COLORS: 'dashboard-colors', // owner: @thmsobrmlr #team-product-analytics
    ERROR_TRACKING_INTEGRATIONS: 'error-tracking-integrations', // owner: @david #team-error-tracking
    ERROR_TRACKING_ALERT_ROUTING: 'error-tracking-alert-routing', // owner: #team-error-tracking
    REPLAY_TRIGGER_TYPE_CHOICE: 'replay-trigger-type-choice', // owner: @pauldambra #team-replay
    POSTHOG_STORIES: 'posthog-stories', // owner: @jabahamondes #team-web-analytics
    ACTIVE_HOURS_HEATMAP: 'active-hours-heatmap', // owner: @jabahamondes #team-web-analytics
    CALENDAR_HEATMAP_INSIGHT: 'calendar-heatmap-insight', // owner: @jabahamondes #team-web-analytics
    WEB_ANALYTICS_MARKETING: 'web-analytics-marketing', // owner: @jabahamondes #team-web-analytics
    BILLING_FORECASTING_ISSUES: 'billing-forecasting-issues', // owner: @pato
    STARTUP_PROGRAM_INTENT: 'startup-program-intent', // owner: @pawel-cebula #team-billing
    SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES: 'web-analytics-pre-aggregated-tables', // owner: @lricoy #team-web-analytics
    SHOW_NEW_EXPERIMENTATION_ENGINE_BANNER: 'show-new-experimentation-engine-banner', // owner: @andehen #team-experiments
    WEB_ANALYTICS_FRUSTRATING_PAGES_TILE: 'web-analytics-frustrating-pages-tile', // owner: @lricoy #team-web-analytics
    SQL_EDITOR_AI_ERROR_FIXER: 'sql-editor-ai-error-fixer', // owner: @Gilbert09 #team-data-warehouse
    GOOGLE_ADS_DWH: 'google-ads-dwh', // owner: @tomasfarias #team-data-warehouse
    DASHBOARD_SYNC_INSIGHT_LOADING: 'dashboard-sync-insight-loading', // owner: @anirudhpillai #team-product-analytics
    ALWAYS_QUERY_BLOCKING: 'always-query-blocking', // owner: @timgl
    GET_HOG_TEMPLATES_FROM_DB: 'get-hog-templates-from-db', // owner: @meikel #team-
    SHOW_COMING_SOON_DESTINATIONS: 'show-coming-soon-destinations', // owner: @meikel #team-cdp
    BLOCKING_EXPORTS: 'blocking-exports', // owner: @aspicer #team-product-analytics
    REPLAY_ACTIVE_HOURS_HEATMAP: 'replay-active-hours-heatmap', // owner: @pauldambra #team-replay
    LINKS: 'links', // owner: @marconlp #team-link
    GAME_CENTER: 'game-center', // owner: everybody
    USER_INTERVIEWS: 'user-interviews', // owner: @Twixes @jurajmajerik
    LOGS: 'logs', // owner: @david @frank @olly @ross
    CSP_REPORTING: 'mexicspo', // owner @pauldambra @lricoy @robbiec
    USER_GROUPS_ENABLED: 'user-groups-enabled', // owner: #team-error-tracking
    LLM_OBSERVABILITY_PLAYGROUND: 'llm-observability-playground', // owner: #team-llm-observability @peter-k
    USAGE_SPEND_DASHBOARDS: 'usage-spend-dashboards', // owner: @pawel-cebula #team-billing
    CDP_HOG_SOURCES: 'cdp-hog-sources', // owner #team-cdp
    CDP_HOG_INPUT_LIQUID: 'cdp-hog-input-liquid', // owner: #team-messaging
    SIMPLE_INFINITE_LIST_NUMERICAL_FILTER: 'simple-infinite-list-numerical-filter', // owner: @rafaeelaudibert #team-revenue-analytics
    REVENUE_ANALYTICS_FILTERS: 'revenue-analytics-filters', // owner: @rafaeelaudibert #team-revenue-analytics
    REPLAY_SCREENSHOT: 'replay-screenshot', // owner: @veryayskiy #team-replay
    SCREENSHOT_EDITOR: 'screenshot-editor', // owner: @veryayskiy #team-replay
    ACTIVITY_OR_EXPLORE: 'activity-or-explore', // owner: @pauldambra #team-replay
    EXPERIMENTS_NEW_QUERY_RUNNER_FOR_USERS_ON_FREE_PLAN: 'experiments-new-query-runner-for-users-on-free-plan', // owner: #team-experiments
    LINEAGE_DEPENDENCY_VIEW: 'lineage-dependency-view', // owner: @phixMe #team-data-warehouse
    TRACK_MEMORY_USAGE: 'track-memory-usage', // owner: @pauldambra #team-replay
    TAXONOMIC_EVENT_SORTING: 'taxonomic-event-sorting', // owner: @pauldambra #team-replay
    SQL_EDITOR_TREE_VIEW: 'sql-editor-tree-view', // owner: @EDsCODE #team-data-warehouse
    AI_HOG_FUNCTION_CREATION: 'ai-hog-function-creation', // owner: @meikel #team-cdp
    REPLAY_FILTERS_IN_PLAYLIST: 'replay-filters-in-playlist', // owner: @veryayskiy #team-replay
    REPLAY_FILTERS_IN_PLAYLIST_MAX_AI: 'replay-filters-in-playlist-max-ai', // owner: @veryayskiy #team-replay
    ANNOTATIONS_RECORDING_SCOPE: 'annotations-recording-scope', // owner: @pauldambra #team-replay,
    EXPERIMENTS_NEW_RUNNER_RESULTS_BREAKDOWN: 'experiments-new-runner-results-breakdown', // owner: @rodrigoi #team-experiments
    REPLAY_ZEN_MODE: 'replay-zen-mode', // owner: @veryayskiy #team-replay
    REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU: 'replay-exclude-from-hide-recordings-menu', // owner: @veryayskiy #team-replay
    USE_TEMPORAL_SUBSCRIPTIONS: 'use-temporal-subscriptions', // owner: @aspicer #team-product-analytics
    EXPERIMENTS_DEV_STATS_METHOD_TOGGLE: 'experiments-dev-stats-method-toggle', // owner: #team-experiments
    REPLAY_EXPORT_RAW_RECORDING: 'replay-export-raw-recording', // owner: @veryayskiy #team-replay
} as const
export type FeatureFlagKey = (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]

export const PRODUCT_VISUAL_ORDER = {
    productAnalytics: 10,
    webAnalytics: 20,
    revenueAnalytics: 30,
    dashboards: 50,
    notebooks: 52,
    sessionReplay: 60,
    featureFlags: 70,
    experiments: 80,
    surveys: 90,
    aiChat: 100,
    llmObservability: 110,
    earlyAccessFeatures: 120,
    errorTracking: 130,
    sqlEditor: 135,
    dataPipeline: 140,
    // alphas
    messaging: 300,
    heatmaps: 310,
    links: 320,
    logs: 330,
    userInterviews: 340,
}

export const INSIGHT_VISUAL_ORDER = {
    trends: 10,
    funnel: 20,
    retention: 30,
    paths: 40,
    stickiness: 50,
    lifecycle: 60,
    calendarHeatmap: 70,
    sql: 80,
    hog: 90,
}

export const ENTITY_MATCH_TYPE = 'entities'
export const PROPERTY_MATCH_TYPE = 'properties'

export enum FunnelLayout {
    horizontal = 'horizontal',
    vertical = 'vertical',
}

export const BIN_COUNT_AUTO = 'auto' as const

export const RETENTION_MEAN_NONE = 'none' as const

// Cohort types
export enum CohortTypeEnum {
    Static = 'static',
    Dynamic = 'dynamic',
}

/**
 * Mock Node.js `process`, which is required by VFile that is used by ReactMarkdown.
 * See https://github.com/remarkjs/react-markdown/issues/339.
 */
export const MOCK_NODE_PROCESS = { cwd: () => '', env: {} } as unknown as NodeJS.Process

export const SSO_PROVIDER_NAMES: Record<SSOProvider, string> = {
    'google-oauth2': 'Google',
    github: 'GitHub',
    gitlab: 'GitLab',
    saml: 'Single sign-on (SAML)',
}

export const DOMAIN_REGEX = /^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$/
export const SECURE_URL_REGEX = /^(?:http(s)?:\/\/)[\w.-]+(?:\.[\w.-]+)+[\w\-._~:/?#[\]@!$&'()*+,;=]+$/gi

export const CLOUD_HOSTNAMES = {
    [Region.US]: 'us.posthog.com',
    [Region.EU]: 'eu.posthog.com',
}

export const SESSION_RECORDINGS_PLAYLIST_FREE_COUNT = 5

export const GENERATED_DASHBOARD_PREFIX = 'Generated Dashboard'

export const ACTIVITY_PAGE_SIZE = 20
export const EVENT_DEFINITIONS_PER_PAGE = 50
export const PROPERTY_DEFINITIONS_PER_EVENT = 5
export const EVENT_PROPERTY_DEFINITIONS_PER_PAGE = 50
export const LOGS_PORTION_LIMIT = 50

export const SESSION_REPLAY_MINIMUM_DURATION_OPTIONS: LemonSelectOptions<number | null> = [
    {
        label: 'no minimum',
        value: null,
    },
    {
        label: '1',
        value: 1000,
    },
    {
        label: '2',
        value: 2000,
    },
    {
        label: '5',
        value: 5000,
    },
    {
        label: '10',
        value: 10000,
    },
    {
        label: '15',
        value: 15000,
    },
    {
        label: '30',
        value: 30000,
    },
]

export const UNSUBSCRIBE_SURVEY_ID = '018b6e13-590c-0000-decb-c727a2b3f462'
export const SESSION_RECORDING_OPT_OUT_SURVEY_ID = '0194a763-9a13-0000-8088-32b52acf7156'
export const SESSION_RECORDING_OPT_OUT_SURVEY_ID_2 = '0195ec93-5f91-0000-15fa-55aaf5e0c562'

export const TAILWIND_BREAKPOINTS = {
    sm: 526,
    md: 768,
    lg: 992,
    xl: 1200,
    '2xl': 1600,
}
