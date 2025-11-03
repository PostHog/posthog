import { LemonSelectOptions } from '@posthog/lemon-ui'

import { ChartDisplayCategory, ChartDisplayType, Region, SSOProvider } from '../types'

// Sync with backend DISPLAY_TYPES_TO_CATEGORIES
export const DISPLAY_TYPES_TO_CATEGORIES: Record<ChartDisplayType, ChartDisplayCategory> = {
    [ChartDisplayType.ActionsLineGraph]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsBar]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsUnstackedBar]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsStackedBar]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsAreaGraph]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsLineGraphCumulative]: ChartDisplayCategory.CumulativeTimeSeries,
    [ChartDisplayType.BoldNumber]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsPie]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsBarValue]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsTable]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.WorldMap]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.CalendarHeatmap]: ChartDisplayCategory.TotalValue,
}
export const NON_TIME_SERIES_DISPLAY_TYPES = Object.entries(DISPLAY_TYPES_TO_CATEGORIES)
    .filter(([, category]) => category === ChartDisplayCategory.TotalValue)
    .map(([displayType]) => displayType as ChartDisplayType)

/** Display types for which `breakdown` is hidden and ignored. Sync with backend NON_BREAKDOWN_DISPLAY_TYPES. */
export const NON_BREAKDOWN_DISPLAY_TYPES = [ChartDisplayType.BoldNumber, ChartDisplayType.CalendarHeatmap]
/** Display types which only work with a single series. */
export const SINGLE_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.CalendarHeatmap,
]

export const NON_VALUES_ON_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.ActionsTable,
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.CalendarHeatmap,
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
export const PERSON_DISPLAY_NAME_COLUMN_NAME = 'person_display_name -- Person'

// Sync with .../api/person.py and .../ingestion/webhook-formatter.ts
export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    'email',
    'Email',
    '$email',
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

/**
 * @deprecated should be removed once backend is updated
 */
export enum ShownAsValue {
    VOLUME = 'Volume',
    STICKINESS = 'Stickiness',
    LIFECYCLE = 'Lifecycle',
}

// Retention constants
export const RETENTION_RECURRING = 'retention_recurring'
// hasn't been renamed to 'retention_first_occurrence_matching_filters' until schema migration
export const RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS = 'retention_first_time'
export const RETENTION_FIRST_EVER_OCCURRENCE = 'retention_first_ever_occurrence'

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
    QUERY_RUNNING_TIME: 'query_running_time', // owner: @mariusandra
    QUERY_TIMINGS: 'query-timings', // owner: @mariusandra
    HEDGEHOG_MODE_DEBUG: 'hedgehog-mode-debug', // owner: @benjackwhite
    HIGH_FREQUENCY_BATCH_EXPORTS: 'high-frequency-batch-exports', // owner: @tomasfarias
    PERSON_BATCH_EXPORTS: 'person-batch-exports', // owner: @tomasfarias
    SESSIONS_BATCH_EXPORTS: 'sessions-batch-exports', // owner: @tomasfarias
    FF_DASHBOARD_TEMPLATES: 'ff-dashboard-templates', // owner: @EDsCODE
    ARTIFICIAL_HOG: 'artificial-hog', // owner: #team-posthog-ai
    SIDEBAR_ANALYTICS_PRIORITIZATION: 'sidebar-analytics-prioritization', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_HIGHER_CONCURRENCY: 'web-analytics-higher-concurrency', // owner: @lricoy #team-web-analytics
    MAX_AI_INSIGHT_SEARCH: 'max-ai-insight-search', // owner: #team-posthog-ai
    PRODUCT_SPECIFIC_ONBOARDING: 'product-specific-onboarding', // owner: @raquelmsmith
    REDIRECT_SIGNUPS_TO_INSTANCE: 'redirect-signups-to-instance', // owner: @raquelmsmith
    HOGQL_DASHBOARD_ASYNC: 'hogql-dashboard-async', // owner: @webjunkie
    WEBHOOKS_DENYLIST: 'webhooks-denylist', // owner: #team-ingestion
    FEATURE_FLAG_COHORT_CREATION: 'feature-flag-cohort-creation', // owner: @neilkakkar #team-feature-success
    INSIGHT_HORIZONTAL_CONTROLS: 'insight-horizontal-controls', // owner: #team-product-analytics
    SURVEYS_ADAPTIVE_LIMITS: 'surveys-adaptive-limits', // owner: #team-surveys
    SURVEY_EMPTY_STATE_V2: 'survey-empty-states-v2', // owner: #team-surveys
    SURVEYS_ACTIONS: 'surveys-actions', // owner: #team-surveys
    EXTERNAL_SURVEYS: 'external-surveys', // owner: #team-surveys
    SURVEY_ANALYSIS_MAX_TOOL: 'survey-analysis-max-tool', // owner: #team-surveys
    DISCUSSIONS: 'discussions', // owner: @daibhin @benjackwhite
    REDIRECT_INSIGHT_CREATION_PRODUCT_ANALYTICS_ONBOARDING: 'redirect-insight-creation-product-analytics-onboarding', // owner: @biancayang
    AI_SESSION_SUMMARY: 'ai-session-summary', // owner: #team-replay
    AI_SESSION_PERMISSIONS: 'ai-session-permissions', // owner: #team-replay
    SESSION_REPLAY_DOCTOR: 'session-replay-doctor', // owner: #team-replay
    AUDIT_LOGS_ACCESS: 'audit-logs-access', // owner: #team-platform-features
    SUBSCRIBE_FROM_PAYGATE: 'subscribe-from-paygate', // owner: #team-billing
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
    QUERY_CACHE_USE_S3: 'query-cache-use-s3', // owner: @aspicer #team-product-analytics
    DASHBOARD_THREADS: 'dashboard-threads', // owner: @aspicer #team-product-analytics
    BATCH_EXPORTS_POSTHOG_HTTP: 'posthog-http-batch-exports',
    BATCH_EXPORTS_DATABRICKS: 'databricks-batch-exports', // owner: @rossgray #team-batch-exports
    HEDGEHOG_SKIN_SPIDERHOG: 'hedgehog-skin-spiderhog', // owner: @benjackwhite
    WEB_EXPERIMENTS: 'web-experiments', // owner: @team-feature-success
    ENVIRONMENTS: 'environments', // owner: #team-platform-features
    REPLAY_TEMPLATES: 'replay-templates', // owner: @raquelmsmith #team-replay
    WORKFLOWS: 'messaging', // owner @haven #team-workflows
    MESSAGING_SES: 'messaging-ses', // owner #team-workflows
    WORKFLOWS_INTERNAL_EVENT_FILTERS: 'workflows-internal-event-filters', // owner: @haven #team-workflows
    ENVIRONMENTS_ROLLBACK: 'environments-rollback', // owner: @yasen-posthog #team-platform-features
    SELF_SERVE_CREDIT_OVERRIDE: 'self-serve-credit-override', // owner: @zach
    CUSTOM_CSS_THEMES: 'custom-css-themes', // owner: @daibhin
    METALYTICS: 'metalytics', // owner: @surbhi
    REMOTE_CONFIG: 'remote-config', // owner: @benjackwhite
    REPLAY_HOGQL_FILTERS: 'replay-hogql-filters', // owner: @pauldambra #team-replay
    REPLAY_GROUPS_FILTERS: 'replay-groups-filters', // owner: @pauldambra #team-replay
    SUPPORT_MESSAGE_OVERRIDE: 'support-message-override', // owner: @abigail
    BILLING_SKIP_FORECASTING: 'billing-skip-forecasting', // owner: @zach
    CDP_ACTIVITY_LOG_NOTIFICATIONS: 'cdp-activity-log-notifications', // owner: #team-workflows-cdp
    BATCH_EXPORT_NEW_LOGS: 'batch-export-new-logs', // owner: #team-batch-exports
    COOKIELESS_SERVER_HASH_MODE_SETTING: 'cookieless-server-hash-mode-setting', // owner: @robbie-c #team-web-analytics
    WEB_ANALYTICS_FOR_MOBILE: 'web-analytics-for-mobile', // owner: @robbie-c #team-web-analytics
    LLM_OBSERVABILITY: 'llm-observability', // owner: #team-llm-analytics
    ONBOARDING_SESSION_REPLAY_SEPARATE_STEP: 'onboarding-session-replay-separate-step', // owner: @joshsny
    EXPERIMENT_INTERVAL_TIMESERIES: 'experiments-interval-timeseries', // owner: @jurajmajerik #team-experiments
    EXPERIMENTAL_DASHBOARD_ITEM_RENDERING: 'experimental-dashboard-item-rendering', // owner: @thmsobrmlr #team-product-analytics
    PATHS_V2: 'paths-v2', // owner: @thmsobrmlr #team-product-analytics
    SCHEMA_MANAGEMENT: 'schema-management', // owner: @aspicer
    SDK_DOCTOR_BETA: 'sdk-doctor-beta', // owner: @slshults
    ONBOARDING_DATA_WAREHOUSE_FOR_PRODUCT_ANALYTICS: 'onboarding-data-warehouse-for-product-analytics', // owner: @joshsny
    DELAYED_LOADING_ANIMATION: 'delayed-loading-animation', // owner: @raquelmsmith
    WEB_ANALYTICS_PAGE_REPORTS: 'web-analytics-page-reports', // owner: @lricoy #team-web-analytics
    ENDPOINTS: 'embedded-analytics', // owner: @sakce #team-clickhouse
    SUPPORT_FORM_IN_ONBOARDING: 'support-form-in-onboarding', // owner: @joshsny
    CRM_ITERATION_ONE: 'crm-iteration-one', // owner: @arthurdedeus #team-customer-analytics
    CRM_USAGE_METRICS: 'crm-usage-metrics', // owner: @arthurdedeus #team-customer-analytics
    TOGGLE_PROPERTY_ARRAYS: 'toggle-property-arrays', // owner: @arthurdedeus #team-customer-analytics
    DWH_JOIN_TABLE_PREVIEW: 'dwh-join-table-preview', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_ANALYTICS: 'customer-analytics', // owner: @arthurdedeus #team-customer-analytics
    SETTINGS_SESSIONS_V2_JOIN: 'settings-sessions-v2-join', // owner: @robbie-c #team-web-analytics
    SAVE_INSIGHT_TASK: 'save-insight-task', // owner: @joshsny
    DASHBOARD_COLORS: 'dashboard-colors', // owner: @thmsobrmlr #team-product-analytics
    ERROR_TRACKING_ALERT_ROUTING: 'error-tracking-alert-routing', // owner: #team-error-tracking
    ERROR_TRACKING_ISSUE_CORRELATION: 'error-tracking-issue-correlation', // owner: @david #team-error-tracking
    ERROR_TRACKING_ISSUE_SPLITTING: 'error-tracking-issue-splitting', // owner: @david #team-error-tracking
    ERROR_TRACKING_ISSUE_LAYOUT_V2: 'error-tracking-issue-layout-v2', // owner: @david #team-error-tracking
    ERROR_TRACKING_REVENUE_SORTING: 'error-tracking-revenue-sorting', // owner: @david #team-error-tracking
    ERROR_TRACKING_RELATED_ISSUES: 'error-tracking-related-issues', // owner: #team-error-tracking
    REPLAY_TRIGGER_TYPE_CHOICE: 'replay-trigger-type-choice', // owner: @pauldambra #team-replay
    CALENDAR_HEATMAP_INSIGHT: 'calendar-heatmap-insight', // owner: @jabahamondes #team-web-analytics
    WEB_ANALYTICS_MARKETING: 'marketing-analytics', // owner: @jabahamondes #team-web-analytics
    WEB_ANALYTICS_TILE_TOGGLES: 'web-analytics-tile-toggles', // owner: @lricoy #team-web-analytics
    BILLING_FORECASTING_ISSUES: 'billing-forecasting-issues', // owner: @pato #team-billing
    STARTUP_PROGRAM_INTENT: 'startup-program-intent', // owner: @pawel-cebula #team-billing
    SHOW_UPGRADE_TO_MANAGED_ACCOUNT: 'show-upgrade-to-managed-account', // owner: @pawel-cebula #team-billing
    SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES: 'web-analytics-pre-aggregated-tables', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_FRUSTRATING_PAGES_TILE: 'web-analytics-frustrating-pages-tile', // owner: @lricoy #team-web-analytics
    ALWAYS_QUERY_BLOCKING: 'always-query-blocking', // owner: @timgl
    GET_HOG_TEMPLATES_FROM_DB: 'get-hog-templates-from-db', // owner: @meikel #team-
    SSE_DASHBOARDS: 'sse-dashboards', // owner: @aspicer #team-product-analytics
    LINKS: 'links', // owner: @marconlp #team-link
    GAME_CENTER: 'game-center', // owner: everybody
    USER_INTERVIEWS: 'user-interviews', // owner: @Twixes @jurajmajerik
    LOGS: 'logs', // owner: #team-logs
    LOGS_PRE_EARLY_ACCESS: 'logs-internal', // owner: #team-logs
    CSP_REPORTING: 'mexicspo', // owner @pauldambra @lricoy @robbiec
    LLM_OBSERVABILITY_PLAYGROUND: 'llm-observability-playground', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS: 'llm-analytics-evaluations', // owner: #team-llm-analytics
    USAGE_SPEND_DASHBOARDS: 'usage-spend-dashboards', // owner: @pawel-cebula #team-billing
    CDP_HOG_SOURCES: 'cdp-hog-sources', // owner #team-workflows-cdp
    CDP_PERSON_UPDATES: 'cdp-person-updates', // owner: #team-workflows-cdp
    ACTIVITY_OR_EXPLORE: 'activity-or-explore', // owner: @pauldambra #team-replay
    LINEAGE_DEPENDENCY_VIEW: 'lineage-dependency-view', // owner: @phixMe #team-data-stack
    TRACK_MEMORY_USAGE: 'track-memory-usage', // owner: @pauldambra #team-replay
    TAXONOMIC_EVENT_SORTING: 'taxonomic-event-sorting', // owner: @pauldambra #team-replay
    REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU: 'replay-exclude-from-hide-recordings-menu', // owner: @veryayskiy #team-replay
    USE_TEMPORAL_SUBSCRIPTIONS: 'use-temporal-subscriptions', // owner: @aspicer #team-product-analytics
    AA_TEST_BAYESIAN_LEGACY: 'aa-test-bayesian-legacy', // owner: #team-experiments
    AA_TEST_BAYESIAN_NEW: 'aa-test-bayesian-new', // owner: #team-experiments
    EXPERIMENTS_AI_SUMMARY: 'experiments-ai-summary', // owner: @rodrigoi #team-experiments
    WEB_ANALYTICS_API: 'web-analytics-api', // owner: #team-web-analytics
    MEMBERS_CAN_USE_PERSONAL_API_KEYS: 'members-can-use-personal-api-keys', // owner: @yasen-posthog #team-platform-features
    FLAG_EVALUATION_RUNTIMES: 'flag-evaluation-runtimes', // owner: @dmarticus #team-feature-flags
    FLAG_EVALUATION_TAGS: 'flag-evaluation-tags', // owner: @dmarticus #team-feature-flags
    DEFAULT_EVALUATION_ENVIRONMENTS: 'default-evaluation-environments', // owner: @dmarticus #team-feature-flags
    PATH_CLEANING_FILTER_TABLE_UI: 'path-cleaning-filter-table-ui', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_CONVERSION_GOAL_PREAGG: 'web-analytics-conversion-goal-preagg', // owner: @lricoy #team-web-analytics
    REPLAY_SETTINGS_HELP: 'replay-settings-help', // owner: @veryayskiy #team-replay
    EDITOR_DRAFTS: 'editor-drafts', // owner: @EDsCODE #team-data-stack
    DATA_WAREHOUSE_SCENE: 'data-warehouse-scene', // owner: @naumaanh #team-data-stack
    MAX_BILLING_CONTEXT: 'max-billing-context', // owner: @pawel-cebula #team-billing
    TASKS: 'tasks', // owner: #team-llm-analytics
    MANAGED_VIEWSETS: 'managed-viewsets', // owner: @rafaeelaudibert #team-revenue-analytics
    LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT: 'llm-observability-show-input-output', // owner: #team-llm-analytics
    MAX_SESSION_SUMMARIZATION: 'max-session-summarization', // owner: #team-posthog-ai
    TASK_SUMMARIES: 'task-summaries', // owner: #team-llm-analytics
    EXPERIMENTS_RATIO_METRIC: 'experiments-ratio-metric', // owner: @andehen #team-experiments
    CDP_NEW_PRICING: 'cdp-new-pricing', // owner: #team-workflows
    IMPROVED_COOKIELESS_MODE: 'improved-cookieless-mode', // owner: @robbie-c #team-web-analytics
    REPLAY_EXPORT_FULL_VIDEO: 'replay-export-full-video', // owner: @veryayskiy #team-replay
    LIVE_DEBUGGER: 'live-debugger', // owner: @marcecoll
    PLATFORM_PAYGATE_CTA: 'platform-paygate-cta', // owner: @a-lider #team-platform-features
    SWITCH_SUBSCRIPTION_PLAN: 'switch-subscription-plan', // owner: @a-lider #team-platform-features
    LLM_ANALYTICS_DATASETS: 'llm-analytics-datasets', // owner: #team-llm-analytics #team-posthog-ai
    LLM_ANALYTICS_SESSIONS_VIEW: 'llm-analytics-sessions-view', // owner: #team-llm-analytics
    AMPLITUDE_BATCH_IMPORT_OPTIONS: 'amplitude-batch-import-options', // owner: #team-ingestion
    MAX_DEEP_RESEARCH: 'max-deep-research', // owner: @kappa90 #team-posthog-ai
    NOTEBOOKS_COLLAPSIBLE_SECTIONS: 'notebooks-collapsible-sections', // owner: @daibhin @benjackwhite
    QUERY_EXECUTION_DETAILS: 'query-execution-details', // owner: @sakce
    PASSWORD_PROTECTED_SHARES: 'password-protected-shares', // owner: @aspicer
    EXPERIMENT_TIMESERIES: 'experiment-timeseries', // owner: @jurajmajerik #team-experiments
    DASHBOARD_TILE_OVERRIDES: 'dashboard-tile-overrides', // owner: @gesh #team-product-analytics
    RECORDINGS_PLAYER_EVENT_PROPERTY_EXPANSION: 'recordings-player-event-property-expansion', // owner: @pauldambra #team-replay
    SCHEDULE_FEATURE_FLAG_VARIANTS_UPDATE: 'schedule-feature-flag-variants-update', // owner: @gustavo #team-feature-flags
    REPLAY_X_LLM_ANALYTICS_CONVERSATION_VIEW: 'replay-x-llm-analytics-conversation-view', // owner: @pauldambra #team-replay
    FLAGGED_FEATURE_INDICATOR: 'flagged-feature-indicator', // owner: @benjackwhite
    SEEKBAR_PREVIEW_SCRUBBING: 'seekbar-preview-scrubbing', // owner: @pauldambra #team-replay
    EXPERIMENTS_BREAKDOWN_FILTER: 'experiments-breakdown-filter', // owner: @rodrigoi #team-experiments
    TARGETED_PRODUCT_UPSELL: 'targeted-product-upsell', // owner: @raquelmsmith
    COHORT_CALCULATION_HISTORY: 'cohort-calculation-history', // owner: @gustavo #team-feature-flags
    EXPERIMENTS_HIDE_STOP_BUTTON: 'experiments-hide-stop-button', // owner: @jurajmajerik #team-experiments
    REPLAY_CLIENT_SIDE_DECOMPRESSION: 'replay-client-side-decompression', // owner: @pauldambra #team-replay
    COHORT_CALCULATION_CHUNKED: 'cohort-calculation-chunked', // owner: @gustavo #team-feature-flags
    EXPERIMENTS_USE_NEW_QUERY_BUILDER: 'experiments-use-new-query-builder', // owner: @andehen #team-experiments
    ADVANCE_MARKETING_ANALYTICS_SETTINGS: 'advance-marketing-analytics-settings', // owner: @jabahamondes  #team-web-analytics
    SHOPIFY_DWH: 'shopify-dwh', // owner: @andrew #team-data-stack
    DWH_FREE_SYNCS: 'dwh-free-syncs', // owner: @Gilbert09  #team-data-stack
    COPY_WEB_ANALYTICS_DATA: 'copy-web-analytics-data', // owner: @lricoy  #team-web-analytics
    EXPERIMENTS_CREATE_FORM: 'experiments-create-form', // owner: @rodrigoi #team-experiments
    REPLAY_FILTERS_REDESIGN: 'replay-filters-redesign', // owner: @ksvat #team-replay
} as const
export type FeatureFlagLookupKey = keyof typeof FEATURE_FLAGS
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
    llmAnalytics: 110,
    earlyAccessFeatures: 120,
    errorTracking: 130,
    sqlEditor: 135,
    dataPipeline: 140,
    // alphas
    workflows: 300,
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
export const SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS = 10 // days

export const GENERATED_DASHBOARD_PREFIX = 'Generated Dashboard'

export const ACTIVITY_PAGE_SIZE = 20
export const ADVANCED_ACTIVITY_PAGE_SIZE = 100
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
export const SESSION_RECORDING_OPT_OUT_SURVEY_ID = '01985c68-bd25-0000-b7e3-f1ccc987e979'
export const TRIAL_CANCELLATION_SURVEY_ID = '019923cd-461c-0000-27ed-ed8e422c596e'

export const TAILWIND_BREAKPOINTS = {
    sm: 526,
    md: 768,
    lg: 992,
    xl: 1200,
    '2xl': 1600,
}

export const INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID = 'insight-alert-firing'
export const INSIGHT_ALERT_DESTINATION_LOGIC_KEY = 'insightAlertDestination'
export const INSIGHT_ALERT_FIRING_EVENT_ID = '$insight_alert_firing'

export const COHORT_PERSONS_QUERY_LIMIT = 10000
