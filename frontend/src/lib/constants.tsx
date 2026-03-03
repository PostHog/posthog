import { LemonSelectOptions } from '@posthog/lemon-ui'

import { ChartDisplayCategory, ChartDisplayType, Region, SDKKey, SSOProvider } from '../types'

// Sync with backend DISPLAY_TYPES_TO_CATEGORIES
export const DISPLAY_TYPES_TO_CATEGORIES: Record<ChartDisplayType, ChartDisplayCategory> = {
    [ChartDisplayType.Auto]: ChartDisplayCategory.TimeSeries,
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
    [ChartDisplayType.TwoDimensionalHeatmap]: ChartDisplayCategory.TotalValue,
}
export const NON_TIME_SERIES_DISPLAY_TYPES = Object.entries(DISPLAY_TYPES_TO_CATEGORIES)
    .filter(([, category]) => category === ChartDisplayCategory.TotalValue)
    .map(([displayType]) => displayType as ChartDisplayType)

/** Display types for which `breakdown` is hidden and ignored. Sync with backend NON_BREAKDOWN_DISPLAY_TYPES. */
export const NON_BREAKDOWN_DISPLAY_TYPES = [
    ChartDisplayType.BoldNumber,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.TwoDimensionalHeatmap,
]
/** Display types which only work with a single series. */
export const SINGLE_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.TwoDimensionalHeatmap,
]

export const NON_VALUES_ON_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.ActionsTable,
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.TwoDimensionalHeatmap,
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

// Sync with .../api/person.py and cdp/utils.ts
export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = ['email', 'name', 'username']

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

// NOTE: Run `dev:sync-flags` locally to sync these flags into your local project
// or if you're running flox + mprocs you can also run the `sync-feature-flags` process
//
// If this is a multivariate flag, please add the `multivariate=true` tag at the end of your comment
// if you want the script to properly create a multivariate flag. You can also specify the different
// variant keys separated by commas, e.g. `multivariate=control,test,something_else`
export const FEATURE_FLAGS = {
    // Eternal feature flags, shouldn't be removed, helpful for debugging/maintenance reasons
    BILLING_FORECASTING_ISSUES: 'billing-forecasting-issues', // owner: #team-billing, see `Billing.tsx`, used to raise a warning when billing is having problems
    HOG: 'hog', // owner: #team-data-stack, see `DebugScene.tsx` and also insights
    QUERY_TIMINGS: 'query-timings', // owner: #team-analytics-platform, usage: see `dataTableLogic.ts`
    REDIRECT_SIGNUPS_TO_INSTANCE: 'redirect-signups-to-instance', // owner: @raquelmsmith, see `signupLogic.ts`
    SESSION_RESET_ON_LOAD: 'session-reset-on-load', // owner: @benjackwhite, usage: see `loadPosthogJS.tsx`
    SETTINGS_PERSONS_ON_EVENTS_HIDDEN: 'settings-persons-on-events-hidden', // owner: #team-platform-features, see `SettingsMap.tsx`
    SUPPORT_MESSAGE_OVERRIDE: 'support-message-override', // owner: #team-support, see `SidePanelSupport.tsx`
    THEME_OVERRIDE: 'theme', // owner: @aprilfools, see `themeLogic.ts`
    USAGE_SPEND_DASHBOARDS: 'usage-spend-dashboards', // owner: #team-billing, see `Billing.tsx`, needed to exclude orgs with more than 100 teams

    // Holidays overrides, will be around forever
    HALLOWEEN_OVERRIDE: 'halloween-override', // owner: #team-growth, overrides the checks for Halloween to return true when this is enabled
    CHRISTMAS_OVERRIDE: 'christmas-override', // owner: #team-growth, overrides the checks for Christmas to return true when this is enabled

    // UX flags, used to control the UX of the app
    AI_FIRST: 'ai-first', // this a larger change, not released to team yet
    SEARCH_AI_PREVIEW: 'search-ai-preview', // used to show AI preview on search when no results are found

    // Feature flags used to control opt-in for different behaviors, should not be removed
    CONTROL_SUPPORT_LOGIN: 'control_support_login', // owner: #team-security, used to control whether users can opt out of support impersonation
    PERSON_PROPERTY_INCIDENT_ANNOTATION_JAN_2026: 'person-property-incident-annotation-jan-2026', // owner: #team-platform-features, shows system annotation for Jan 6-7 2026 person property incident
    AUDIT_LOGS_ACCESS: 'audit-logs-access', // owner: #team-platform-features, used to control access to audit logs
    CUSTOM_CSS_THEMES: 'custom-css-themes', // owner: #team-growth, used to enable custom CSS for teams who want to have fun
    GAME_CENTER: 'game-center', // owner: everybody, this is just internal for now
    HEDGEHOG_SKIN_SPIDERHOG: 'hedgehog-skin-spiderhog', // owner: #team-web-analytics, used to reward beta users for web analytics
    HIGH_FREQUENCY_BATCH_EXPORTS: 'high-frequency-batch-exports', // owner: #team-batch-exports, allow batch exports to be run every 5min
    BATCH_EXPORT_EARLIEST_BACKFILL: 'batch-export-earliest-backfill', // owner: #team-batch-exports, allow backfilling from beginning of time
    METALYTICS: 'metalytics', // owner: #team-platform-features, used to allow companies to see (meta) analytics on access to a specific page
    REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU: 'replay-exclude-from-hide-recordings-menu', // owner: #team-replay, used to exclude what other people are seeing in Replay
    SELF_SERVE_CREDIT_OVERRIDE: 'self-serve-credit-override', // owner: #team-platform-features, used to allow users to self-serve credits even when they don't qualify
    SHOW_UPGRADE_TO_MANAGED_ACCOUNT: 'show-upgrade-to-managed-account', // owner: #team-billing, used to give free accounts a way to force upgrade to managed account
    WEBHOOKS_DENYLIST: 'webhooks-denylist', // owner: #team-ingestion, used to disable webhooks for certain companies

    // Legacy flags, TBD if they need to be removed
    BATCH_EXPORTS_POSTHOG_HTTP: 'posthog-http-batch-exports', // owner: #team-batch-exports
    BILLING_SKIP_FORECASTING: 'billing-skip-forecasting', // owner: @zach
    CALENDAR_HEATMAP_INSIGHT: 'calendar-heatmap-insight', // owner: @jabahamondes #team-web-analytics
    COOKIELESS_SERVER_HASH_MODE_SETTING: 'cookieless-server-hash-mode-setting', // owner: #team-web-analytics
    CSP_REPORTING: 'mexicspo', // owner @pauldambra @lricoy @robbiec
    ERROR_TRACKING_ALERT_ROUTING: 'error-tracking-alert-routing', // owner: #team-error-tracking
    EXPERIMENT_INTERVAL_TIMESERIES: 'experiments-interval-timeseries', // owner: @jurajmajerik #team-experiments
    /* The below flag is used to activate unmounting charts outside the viewport, as we're currently investigating frontend performance
    issues related to this and want to know the impact of having it on vs. off. */
    EXPERIMENTAL_DASHBOARD_ITEM_RENDERING: 'experimental-dashboard-item-rendering', // owner: @thmsobrmlr #team-product-analytics
    IMPROVED_COOKIELESS_MODE: 'improved-cookieless-mode', // owner: #team-web-analytics
    LINEAGE_DEPENDENCY_VIEW: 'lineage-dependency-view', // owner: #team-data-stack
    MEMBERS_CAN_USE_PERSONAL_API_KEYS: 'members-can-use-personal-api-keys', // owner: @yasen-posthog #team-platform-features
    GATEWAY_PERSONAL_API_KEY: 'gateway-personal-api-key', // owner: #team-platform-features
    PERSONLESS_EVENTS_NOT_SUPPORTED: 'personless-events-not-supported', // owner: #team-analytics-platform
    QUERY_RUNNING_TIME: 'query_running_time', // owner: #team-analytics-platform
    REPLAY_HOGQL_FILTERS: 'replay-hogql-filters', // owner: @pauldambra #team-replay
    REPLAY_SETTINGS_HELP: 'replay-settings-help', // owner: @veryayskiy #team-replay
    REPLAY_TRIGGER_TYPE_CHOICE: 'replay-trigger-type-choice', // owner: @pauldambra #team-replay
    SESSION_REPLAY_DOCTOR: 'session-replay-doctor', // owner: #team-replay
    SETTINGS_BOUNCE_RATE_PAGE_VIEW_MODE: 'settings-bounce-rate-page-view-mode', // owner: #team-web-analytics
    SETTINGS_PERSONS_JOIN_MODE: 'settings-persons-join-mode', // owner: #team-analytics-platform
    SETTINGS_SESSION_TABLE_VERSION: 'settings-session-table-version', // owner: #team-analytics-platform
    SETTINGS_SESSIONS_V2_JOIN: 'settings-sessions-v2-join', // owner: @robbie-c #team-web-analytics
    SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES: 'web-analytics-pre-aggregated-tables', // owner: @lricoy #team-web-analytics
    STARTUP_PROGRAM_INTENT: 'startup-program-intent', // owner: @pawel-cebula #team-billing
    SURVEYS_ACTIONS: 'surveys-actions', // owner: #team-surveys
    SURVEYS_ADAPTIVE_LIMITS: 'surveys-adaptive-limits', // owner: #team-surveys
    SURVEYS_GUIDED_EDITOR: 'surveys-guided-editor', // owner: #team-surveys, enables the new simplified survey guided editor
    SURVEYS_REDESIGNED_VIEW: 'surveys-redesigned-view', // owner: #team-surveys, enables the redesigned survey view with sidebar
    TRACK_MEMORY_USAGE: 'track-memory-usage', // owner: @pauldambra #team-replay
    TRACK_REACT_FRAMERATE: 'track-react-framerate', // owner: @pauldambra #team-replay
    WEB_ANALYTICS_API: 'web-analytics-api', // owner: #team-web-analytics
    WEB_ANALYTICS_FOR_MOBILE: 'web-analytics-for-mobile', // owner: #team-web-analytics
    WEB_EXPERIMENTS: 'web-experiments', // owner: #team-experiments

    // Temporary feature flags, still WIP, should be removed eventually
    AA_TEST_BAYESIAN_LEGACY: 'aa-test-bayesian-legacy', // owner: #team-experiments
    AA_TEST_BAYESIAN_NEW: 'aa-test-bayesian-new', // owner: #team-experiments
    ADVANCE_MARKETING_ANALYTICS_SETTINGS: 'advance-marketing-analytics-settings', // owner: @jabahamondes  #team-web-analytics
    APPROVALS: 'approvals', // owner: @yasen-posthog #team-platform-features
    AI_ONLY_MODE: 'ai-only-mode', // owner: #team-posthog-ai
    AI_SESSION_SUMMARY: 'ai-session-summary', // owner: #team-replay
    ALERTS_INLINE_NOTIFICATIONS: 'alerts-inline-notifications', // owner: @vdekrijger
    AMPLITUDE_BATCH_IMPORT_OPTIONS: 'amplitude-batch-import-options', // owner: #team-ingestion
    BATCH_EXPORT_NEW_LOGS: 'batch-export-new-logs', // owner: #team-batch-exports
    BATCH_EXPORTS_AZURE_BLOB: 'azure-blob-batch-exports', // owner: #team-batch-exports
    BATCH_EXPORTS_DATABRICKS: 'databricks-batch-exports', // owner: @rossgray #team-batch-exports
    BACKFILL_WORKFLOWS_DESTINATION: 'backfill-workflows-destination', // owner: #team-batch-exports
    BING_ADS_SOURCE: 'bing-ads-source', // owner: @jabahamondes #team-web-analytics
    CDP_ACTIVITY_LOG_NOTIFICATIONS: 'cdp-activity-log-notifications', // owner: #team-workflows-cdp
    CDP_HOG_SOURCES: 'cdp-hog-sources', // owner #team-workflows-cdp
    CDP_VERCEL_LOG_DRAIN: 'cdp-vercel-log-drain', // owner: #team-workflows-cdp
    CDP_NEW_PRICING: 'cdp-new-pricing', // owner: #team-workflows
    CDP_PERSON_UPDATES: 'cdp-person-updates', // owner: #team-workflows-cdp
    CDP_DWH_TABLE_SOURCE: 'cdp-dwh-table-source', // owner: #team-workflows-cdp
    COHORT_CALCULATION_HISTORY: 'cohort-calculation-history', // owner: @gustavo #team-feature-flags
    COHORT_EMAIL_LOOKUP_CLICKHOUSE: 'cohort-email-lookup-clickhouse', // owner: @gustavo #team-feature-flags
    COHORT_INLINE_CALCULATION: 'inline-cohort-calculation', // owner: #team-analytics-platform, inlines fast dynamic cohort queries instead of using precomputed cohortpeople table
    CONDENSED_FILTER_BAR: 'condensed_filter_bar', // owner: @jordanm-posthog #team-web-analytics
    CREATE_FORM_TOOL: 'phai-create-form-tool', // owner: @kappa90 #team-posthog-ai
    CRM_ITERATION_ONE: 'crm-iteration-one', // owner: @arthurdedeus #team-customer-analytics
    CUSTOM_PRODUCTS_SIDEBAR: 'custom-products-sidebar', // owner: @rafaeelaudibert #team-growth
    CUSTOMER_ANALYTICS: 'customer-analytics-roadmap', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_ANALYTICS_JOURNEYS: 'customer-analytics-journeys', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_PROFILE_CONFIG_BUTTON: 'customer-profile-config-button', // owner: @arthurdedeus #team-customer-analytics
    DATA_MODELING_TAB: 'data-modeling-tab', // owner: #team-data-modeling
    DATA_WAREHOUSE_SCENE: 'data-warehouse-scene', // owner: #team-data-stack
    DEFAULT_EVALUATION_ENVIRONMENTS: 'default-evaluation-environments', // owner: @dmarticus #team-feature-flags
    DROP_PERSON_LIST_ORDER_BY: 'drop-person-list-order-by', // owner: @arthurdedeus #team-customer-analytics
    DWH_FREE_SYNCS: 'dwh-free-syncs', // owner: @Gilbert09  #team-data-stack
    DWH_JOIN_TABLE_PREVIEW: 'dwh-join-table-preview', // owner: @arthurdedeus #team-customer-analytics
    EDITOR_DRAFTS: 'editor-drafts', // owner: @EDsCODE #team-data-stack
    ENDPOINTS: 'embedded-analytics', // owner: @sakce #team-clickhouse
    ERROR_TRACKING_ISSUE_CORRELATION: 'error-tracking-issue-correlation', // owner: @david #team-error-tracking
    ERROR_TRACKING_ISSUE_SPLITTING: 'error-tracking-issue-splitting', // owner: @david #team-error-tracking
    ERROR_TRACKING_JIRA_INTEGRATION: 'error-tracking-jira-integration', // owner: #team-error-tracking
    ERROR_TRACKING_RELATED_ISSUES: 'error-tracking-related-issues', // owner: #team-error-tracking
    ERROR_TRACKING_INGESTION_CONTROLS: 'error-tracking-ingestion-controls', // owner: #team-error-tracking
    ERROR_TRACKING_REVENUE_SORTING: 'error-tracking-revenue-sorting', // owner: @david #team-error-tracking
    ERROR_TRACKING_SPIKE_ALERTING: 'error-tracking-spike-alerting', // owner: #team-error-tracking
    ERROR_TRACKING_WEEKLY_DIGEST: 'error-tracking-weekly-digest', // owner: #team-error-tracking
    ERROR_TRACKING_ALERTS_WIZARD: 'error-tracking-alerts-wizard', // owner: @aleks #team-error-tracking
    EVENT_MEDIA_PREVIEWS: 'event-media-previews', // owner: @alexlider
    EXPERIMENT_AI_ANALYSIS_TAB: 'experiment-ai-analysis-tab', // owner: @rodrigoi #team-experiments
    EXPERIMENTS_FF_CROSS_SELL: 'experiments-ff-cross-sell', // owner: @rodrigoi #team-experiments
    EXPERIMENT_QUERY_PREAGGREGATION: 'experiment-query-preaggregation', // owner: @jurajmajerik #team-experiments
    EXPERIMENTS_SHOW_SQL: 'experiments-show-sql', // owner: @jurajmajerik #team-experiments
    EXPERIMENTS_TEMPLATES: 'experiments-templates', // owner: @rodrigoi #team-experiments
    EXPERIMENTS_WIZARD_CREATION_FORM: 'experiments-wizard-creation-form', // owner: @mp-hog #team-experiments
    FEATURE_FLAG_COHORT_CREATION: 'feature-flag-cohort-creation', // owner: #team-feature-flags
    FEATURE_FLAGS_V2: 'feature-flags-v2', // owner: @dmarticus #team-feature-flags
    FEATURE_FLAG_USAGE_DASHBOARD_CHECKBOX: 'feature-flag-usage-dashboard-checkbox', // owner: #team-feature-flags, globally disabled, enables opt-out of auto dashboard creation
    FLAG_BUCKETING_IDENTIFIER: 'flag-bucketing-identifier', // owner: @andehen #team-experiments
    FLAG_EVALUATION_RUNTIMES: 'flag-evaluation-runtimes', // owner: @dmarticus #team-feature-flags
    FLAG_EVALUATION_TAGS: 'flag-evaluation-tags', // owner: @dmarticus #team-feature-flags
    FLAGGED_FEATURE_INDICATOR: 'flagged-feature-indicator', // owner: @benjackwhite
    INSIGHT_OPTIONS_PAGE: 'insight-options-page', // owner: @rafaeelaudibert #team-growth multivariate=true
    PRODUCT_ANALYTICS_HOME_TAB: 'product-analytics-home-tab', // owner: @anirudhpillai #team-product-analytics
    INTER_PROJECT_TRANSFERS: 'inter-project-transfers', // owner: @reecejones #team-platform-features
    LINKS: 'links', // owner: @marconlp #team-link (team doesn't exist for now, maybe will come back in the future)
    LIVE_DEBUGGER: 'live-debugger', // owner: @marcecoll
    LIVESTREAM_TUI: 'livestream-tui', // owner: @rafaeelaudibert #team-growth
    LLM_ANALYTICS_DATASETS: 'llm-analytics-datasets', // owner: #team-llm-analytics #team-posthog-ai
    LLM_ANALYTICS_DISCUSSIONS: 'llm-analytics-discussions', // owner: #team-llm-analytics
    LLM_ANALYTICS_EARLY_ADOPTERS: 'llm-analytics-early-adopters', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS: 'llm-analytics-evaluations', // owner: #team-llm-analytics
    LLM_ANALYTICS_OFFLINE_EVALS: 'llm-analytics-offline-evals', // owner: #team-llm-analytics
    LLM_ANALYTICS_TRACE_NAVIGATION: 'llm-analytics-trace-navigation', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS_CUSTOM_MODELS: 'llm-analytics-evaluations-custom-models', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS_ONBOARDING_EXPERIMENT: 'llm-analytics-evaluations-onboarding-experiment', // owner: #team-llm-analytics, multivariate=control,test-b,test-c
    LLM_ANALYTICS_EVALUATIONS_SUMMARY: 'llm-analytics-evaluations-summary', // owner: #team-llm-analytics
    LLM_ANALYTICS_SESSION_SUMMARIZATION: 'llm-analytics-session-summarization', // owner: #team-llm-analytics
    LLM_ANALYTICS_CLUSTERS_TAB: 'llm-analytics-clusters-tab', // owner: #team-llm-analytics
    LLM_ANALYTICS_TOOLS_TAB: 'llm-analytics-tools-tab', // owner: #team-llm-analytics
    LLM_ANALYTICS_CLUSTERING_ADMIN: 'llm-analytics-clustering-admin', // owner: #team-llm-analytics
    LLM_ANALYTICS_SESSIONS_VIEW: 'llm-analytics-sessions-view', // owner: #team-llm-analytics
    LLM_ANALYTICS_SUMMARIZATION: 'llm-analytics-summarization', // owner: #team-llm-analytics
    LLM_ANALYTICS_TEXT_VIEW: 'llm-analytics-text-view', // owner: #team-llm-analytics
    LLM_ANALYTICS_TRANSLATION: 'llm-analytics-translation', // owner: #team-llm-analytics
    PROMPT_MANAGEMENT: 'prompt-management', // owner: #team-llm-analytics
    LLM_ANALYTICS_SENTIMENT: 'llm-analytics-sentiment', // owner: #team-llm-analytics
    LLM_ANALYTICS_USER_FEEDBACK: 'llm-analytics-user-feedback', // owner: @adboio #team-surveys
    LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT: 'llm-observability-show-input-output', // owner: #team-llm-analytics
    LOGS: 'logs', // owner: #team-logs
    NEW_LOGS_DATE_RANGE_PICKER: 'new-logs-date-range-picker', // owner: #team-logs
    LOGS_SETTINGS: 'logs-settings', // owner: #team-logs
    LOGS_SETTINGS_JSON: 'logs-settings-json', // owner: #team-logs
    LOGS_SETTINGS_RETENTION: 'logs-settings-retention', // owner: #team-logs
    LOGS_SPARKLINE_SERVICE_BREAKDOWN: 'logs-sparkline-service-breakdown', // owner: #team-logs
    MCP_SERVERS: 'mcp-servers', // owner: #team-posthog-ai
    MANAGED_VIEWSETS: 'managed-viewsets', // owner: @rafaeelaudibert #team-revenue-analytics
    MAX_AI_INSIGHT_SEARCH: 'max-ai-insight-search', // owner: #team-posthog-ai
    MAX_BILLING_CONTEXT: 'max-billing-context', // owner: @pawel-cebula #team-billing
    MAX_DEEP_RESEARCH: 'max-deep-research', // owner: @kappa90 #team-posthog-ai
    MAX_SESSION_SUMMARIZATION: 'max-session-summarization', // owner: #team-signals
    MAX_SESSION_SUMMARIZATION_BUTTON: 'max-session-summarization-button', // owner: #team-signals
    MAX_SESSION_SUMMARIZATION_VIDEO_AS_BASE: 'max-session-summarization-video-as-base', // owner: #team-signals
    PRODUCT_AUTONOMY: 'product-autonomy', // owner: #team-signals
    MEMBERS_PAGE_PLATFORM_ADDON_AD: 'members-page-platform-addon-ad', // owner: @reecejones #team-platform-features multivariate=control,test-audit-trail,test-paper-trail,test-space-scale,test-big-village
    MESSAGING_SES: 'messaging-ses', // owner #team-workflows
    NOTEBOOKS_COLLAPSIBLE_SECTIONS: 'notebooks-collapsible-sections', // owner: @benjackwhite
    NOTEBOOK_PYTHON: 'notebook-python', // owner: #team-data-tools
    PAGE_REPORTS_AVERAGE_PAGE_VIEW: 'page-reports-average-page-view', // owner: @jordanm-posthog #team-web-analytics
    PHAI_ERROR_TRACKING_MODE: 'posthog-ai-error-tracking-mode', // owner: #team-posthog-ai
    PHAI_LLM_ANALYTICS_MODE: 'posthog-ai-llm-analytics-mode', // owner: #team-posthog-ai
    PHAI_PLAN_MODE: 'phai-plan-mode', // owner: #team-posthog-ai
    PHAI_SURVEY_MODE: 'posthog-ai-survey-mode', // owner: #team-posthog-ai
    PHAI_TASKS: 'phai-tasks', // owner: #team-array
    PHAI_WEB_SEARCH: 'phai-web-search', // owner: @Twixes #team-posthog-ai
    PRODUCT_ANALYTICS_AI_INSIGHT_ANALYSIS: 'product-analytics-ai-insight-analysis', // owner: #team-analytics-platform, used to show AI analysis section in insights
    PRODUCT_ANALYTICS_AUTONAME_INSIGHTS_WITH_AI: 'autoname-insights-with-ai', // owner: @gesh #team-product-analytics
    PRODUCT_ANALYTICS_DASHBOARD_COLORS: 'dashboard-colors', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_ANALYTICS_DATE_PICKER_EXPLICIT_DATE_TOGGLE: 'date-picker-explicit-date-toggle', // owner: @gesh #team-product-analytics
    PRODUCT_ANALYTICS_EVENTS_COMBINATION_IN_TRENDS: 'events-combination-in-trends', // owner: @gesh #team-product-analytics
    PRODUCT_ANALYTICS_EVENTS_COMBINATION_IN_FUNNELS: 'events-combination-in-funnels', // owner: @gesh #team-product-analytics
    PRODUCT_ANALYTICS_FUNNEL_DWH_SUPPORT: 'funnel-dwh-support', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_ANALYTICS_FUNNEL_DWH_STEP_UI: 'funnel-dwh-step-ui', // owner: @thmsobrmlr #team-product-analytics multivariate=control,popover
    PRODUCT_ANALYTICS_INSIGHT_HORIZONTAL_CONTROLS: 'insight-horizontal-controls', // owner: #team-product-analytics
    PRODUCT_ANALYTICS_PATHS_V2: 'paths-v2', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_ANALYTICS_RETENTION_AGGREGATION: 'retention-aggregation', // owner: @anirudhpillai #team-product-analytics
    PRODUCT_ANALYTICS_DASHBOARD_AI_ANALYSIS: 'product-analytics-dashboard-ai-analysis', // owner: @anirudhpillai #team-product-analytics
    PRODUCT_CONVERSATIONS: 'product-conversations', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT: 'product-support-release', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_SIDE_PANEL: 'product-support-side-panel', // owner: @veryayskiy #team-conversations
    ONBOARDING_AI_PRODUCT_RECOMMENDATIONS: 'onboarding-ai-product-recommendations', // owner: @rafaeelaudibert #team-growth, AI-powered product recommendations in onboarding multivariate=control,test,chat
    ONBOARDING_PRODUCT_SELECTION_HEADING: 'onboarding-product-selection-heading', // owner: #team-growth, payload overrides the heading copy on the first onboarding page
    ONBOARDING_REVERSE_PROXY: 'onboarding-reverse-proxy', // owner: @rafaeelaudibert #team-growth
    ONBOARDING_SESSION_REPLAY_MEDIA: 'onboarding-session-replay-media', // owner: @fercgomes #team-growth multivariate=control,screenshot,demo
    ONBOARDING_SKIP_INSTALL_STEP: 'onboarding-skip-install-step', // owner: @rafaeelaudibert #team-growth multivariate=true
    PASSKEY_SIGNUP_ENABLED: 'passkey-signup-enabled', // owner: @reecejones #team-platform-features
    PASSWORD_PROTECTED_SHARES: 'password-protected-shares', // owner: @aspicer
    DASHBOARD_TILE_REDESIGN: 'dashboard-tile-redesign', // owner: @sam #team-product-analytics
    PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS: 'product-analytics-dashboard-modal-smart-defaults', // owner: @sam #team-product-analytics
    PRODUCT_TOURS: 'product-tours-2025', // owner: @adboio #team-surveys
    PRODUCT_TOURS_LOCALIZATION: 'product-tours-localization', // owner: @adboio #team-surveys
    PROJECT_UPGRADE_MODAL_REDESIGN: 'project-upgrade-modal-redesign', // owner: @reecejones #team-platform-features
    POSTHOG_AI_BILLING_DISPLAY: 'posthog-ai-billing-display', // owner: #team-posthog-ai
    POSTHOG_AI_CHANGELOG: 'posthog-ai-changelog', // owner: #team-posthog-ai
    POSTHOG_AI_ALERTS: 'posthog-ai-alerts', // owner: #team-posthog-ai
    POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG: 'posthog-ai-conversation-feedback-config', // owner: #team-posthog-ai
    POSTHOG_AI_CONVERSATION_FEEDBACK_LLMA_SESSIONS: 'posthog-ai-conversation-feedback-llma-sessions', // owner: #team-posthog-ai
    POSTHOG_AI_QUEUE_MESSAGES_SYSTEM: 'posthog-ai-queue-messages-system', // owner: #team-posthog-ai
    POSTHOG_AI_FLAGS_MODE: 'posthog-ai-flags-mode', // owner: #team-posthog-ai
    RBAC_UI_REDESIGN: 'rbac-ui-redesign', // owner: @reece #team-platform-features
    RECORDINGS_PLAYER_EVENT_PROPERTY_EXPANSION: 'recordings-player-event-property-expansion', // owner: @pauldambra #team-replay
    REMOTE_CONFIG: 'remote-config', // owner: #team-platform-features
    REPLAY_FILTERS_REDESIGN: 'replay-filters-redesign', // owner: @ksvat #team-replay
    REPLAY_JIRA_INTEGRATION: 'replay-jira-integration', // owner: @fasyy612 #team-replay, used to enable Jira issue creation from session recordings
    REPLAY_NEW_DETECTED_URL_COLLECTIONS: 'replay-new-detected-url-collections', // owner: @ksvat #team-replay multivariate=true
    REPLAY_SNAPSHOT_STORE: 'replay-snapshot-store', // owner: @tue #team-replay multivariate=control,test
    REPLAY_WAIT_FOR_IFRAME_READY: 'replay-wait-for-full-snapshot-playback', // owner: @ksvat #team-replay
    REPLAY_X_LLM_ANALYTICS_CONVERSATION_VIEW: 'replay-x-llm-analytics-conversation-view', // owner: @pauldambra #team-replay
    REPLAY_COLLAPSE_INSPECTOR_ITEMS: 'replay-collapse-inspector-items', // owner: @fasyy612 #team-replay
    REPLAY_UI_REDESIGN_2026: 'replay-ui-redesign-2026', // owner: #team-replay, New UI layout for replay
    REORDER_PLATFORM_ADDON_BILLING_SECTION: 'reorder-platform-addon-billing-section', // owner: @reece #team-platform-features
    REVENUE_ANALYTICS: 'revenue-analytics', // owner: @rafaeelaudibert #team-customer-analytics
    REVENUE_FIELDS_IN_POWER_USERS_TABLE: 'revenue-fields-in-power-users-table', // owner: @arthurdedeus #team-customer-analytics
    SCHEDULE_FEATURE_FLAG_VARIANTS_UPDATE: 'schedule-feature-flag-variants-update', // owner: @gustavo #team-feature-flags
    SCHEMA_MANAGEMENT: 'schema-management', // owner: @aspicer
    SEEKBAR_PREVIEW_SCRUBBING: 'seekbar-preview-scrubbing', // owner: @pauldambra #team-replay
    SEMVER_TARGETING: 'semver-targeting', // owner: #team-feature-flags
    SHOPIFY_DWH: 'shopify-dwh', // owner: @andrew #team-data-stack
    SHOW_DATA_PIPELINES_NAV_ITEM: 'show-data-pipelines-nav-item', // owner: @raquelmsmith
    SHOW_REFERRER_FAVICON: 'show-referrer-favicon', // owner: @jordanm-posthog #team-web-analytics
    SHOW_REPLAY_FILTERS_FEEDBACK_BUTTON: 'show-replay-filters-feedback-button', // owner: @ksvat #team-replay
    SIGNUP_AA_TEST: 'signup-aa-test', // owner: @andehen #team-experiments multivariate=control,test
    PIPELINE_STATUS_PAGE: 'pipeline-status-page', // owner: @clr182 #team-support
    PINTEREST_ADS_SOURCE: 'pinterest-ads-source', // owner: @jabahamondes #team-web-analytics
    SNAPCHAT_ADS_SOURCE: 'snapchat-ads-source', // owner: @jabahamondes #team-web-analytics
    SQL_EDITOR_VIM_MODE: 'sql-editor-vim-mode', // owner: @arthurdedeus
    SSE_DASHBOARDS: 'sse-dashboards', // owner: @aspicer #team-analytics-platform
    SURVEYS_ERROR_TRACKING_CROSS_SELL: 'surveys-in-error-tracking', // owner: @adboio #team-surveys
    SURVEYS_FORM_BUILDER: 'surveys-form-builder', // owner: @adboio #team-surveys
    SURVEY_HEADLINE_SUMMARY: 'survey-headline-summary', // owner: @adboio #team-surveys
    SURVEYS_INSIGHT_BUTTON_EXPERIMENT: 'ask-users-why-ai-vs-quickcreate', // owner: @adboio #team-surveys multivariate=true
    SURVEYS_WEB_ANALYTICS_CROSS_SELL: 'surveys-in-web-analytics', // owner: @adboio #team-surveys
    TASK_SUMMARIES: 'task-summaries', // owner: #team-llm-analytics
    TASK_TOOL: 'phai-task-tool', // owner: @kappa90 #team-posthog-ai
    TASKS: 'tasks', // owner: #team-llm-analytics
    TOGGLE_PROPERTY_ARRAYS: 'toggle-property-arrays', // owner: @arthurdedeus #team-customer-analytics
    UNIFIED_HEALTH_PAGE: 'unified-health-page', // owner: @jordanm-posthog #team-web-analytics
    USER_INTERVIEWS: 'user-interviews', // owner: @Twixes @jurajmajerik
    WEB_ANALYTICS_CONVERSION_GOAL_PREAGG: 'web-analytics-conversion-goal-preagg', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_EMPTY_ONBOARDING: 'web-analytics-empty-onboarding', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_HEALTH_TAB: 'web_analytics_health_tab', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_LIVE_METRICS: 'web-analytics-live-metrics', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_MARKETING: 'marketing-analytics', // owner: @jabahamondes #team-web-analytics
    WEB_ANALYTICS_OPEN_URL: 'web-analytics-open-url', // owner: @lricoy #team-web-analytics
    NEW_TEAM_CORE_EVENTS: 'new-team-core-events', // owner: @jabahamondes #team-web-analytics
    WEB_ANALYTICS_FILTERS_V2: 'web-analytics-filters-v2', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_SESSION_PROPERTY_CHARTS: 'web-analytics-session-property-charts', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_TILE_TOGGLES: 'web-analytics-tile-toggles', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_REGIONS_MAP: 'web-analytics-regions-map', // owner: @jordanm-posthog #team-web-analytics
    WORKFLOWS_BATCH_TRIGGERS: 'workflows-batch-triggers', // owner: #team-workflows
    WORKFLOWS_INTERNAL_EVENT_FILTERS: 'workflows-internal-event-filters', // owner: @haven #team-workflows
    WORKFLOWS_PERSON_TIMEZONE: 'workflows-person-timezone', // owner: #team-workflows
    WORKFLOWS_PUSH_NOTIFICATIONS: 'workflows-push-notifications', // owner: @Odin #team-workflows
    AVERAGE_PAGE_VIEW_COLUMN: 'average-page-view-column', // owner: @jordanm-posthog #team-web-analytics
    EXPERIMENTS_SAMPLE_RATIO_MISMATCH: 'experiments-sample-ratio-mismatch', // owner: @jurajmajerik #team-experiments
    NEW_TAB_PROJECT_EXPLORER: 'new-tab-project-explorer', // owner: #team-platform-ux
    // PLEASE KEEP THIS ALPHABETICALLY ORDERED
} as const
export type FeatureFlagLookupKey = keyof typeof FEATURE_FLAGS
export type FeatureFlagKey = (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]

export const STORYBOOK_FEATURE_FLAGS = Object.values(FEATURE_FLAGS).filter(
    (flag) => flag !== FEATURE_FLAGS.AI_ONLY_MODE
)

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

/** Maps SDK keys to their corresponding snippet language identifiers */
export const SDK_KEY_TO_SNIPPET_LANGUAGE: Partial<Record<SDKKey, string>> = {
    [SDKKey.JS_WEB]: 'javascript',
    [SDKKey.REACT]: 'react',
    [SDKKey.NODE_JS]: 'node.js',
    [SDKKey.HONO]: 'node.js',
    [SDKKey.PYTHON]: 'python',
    [SDKKey.PHP]: 'php',
    [SDKKey.RUBY]: 'ruby',
    [SDKKey.RUBY_ON_RAILS]: 'ruby',
    [SDKKey.GO]: 'go',
    [SDKKey.ANDROID]: 'android',
    [SDKKey.IOS]: 'ios',
    [SDKKey.REACT_NATIVE]: 'react-native',
    [SDKKey.FLUTTER]: 'flutter',
    [SDKKey.ANGULAR]: 'javascript',
    [SDKKey.ASTRO]: 'javascript',
    [SDKKey.BUBBLE]: 'javascript',
    [SDKKey.DJANGO]: 'python',
    [SDKKey.FRAMER]: 'javascript',
    [SDKKey.LARAVEL]: 'php',
    [SDKKey.NEXT_JS]: 'javascript',
    [SDKKey.NUXT_JS]: 'javascript',
    [SDKKey.NUXT_JS_36]: 'javascript',
    [SDKKey.REMIX]: 'javascript',
    [SDKKey.SVELTE]: 'javascript',
    [SDKKey.VUE_JS]: 'javascript',
    [SDKKey.WEBFLOW]: 'javascript',
    [SDKKey.API]: 'javascript',
    [SDKKey.TANSTACK_START]: 'react',
    [SDKKey.VITE]: 'react',
}
