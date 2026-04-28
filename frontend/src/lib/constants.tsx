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
    [ChartDisplayType.BoxPlot]: ChartDisplayCategory.TimeSeries,
}
export const NON_TIME_SERIES_DISPLAY_TYPES = Object.entries(DISPLAY_TYPES_TO_CATEGORIES)
    .filter(([, category]) => category === ChartDisplayCategory.TotalValue)
    .map(([displayType]) => displayType as ChartDisplayType)

/** Display types for which `breakdown` is hidden and ignored. Sync with backend NON_BREAKDOWN_DISPLAY_TYPES. */
export const NON_BREAKDOWN_DISPLAY_TYPES = [
    ChartDisplayType.BoldNumber,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.TwoDimensionalHeatmap,
    ChartDisplayType.BoxPlot,
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

// NOTE: Run `dev:sync-flags` locally to sync these flags into your local project
// or if you're running flox + phrocs you can also run the `sync-feature-flags` process
//
// If this is a multivariate flag, please add the `multivariate=true` tag at the end of your comment
// if you want the script to properly create a multivariate flag. You can also specify the different
// variant keys separated by commas, e.g. `multivariate=control,test,something_else`
export const FEATURE_FLAGS = {
    // Eternal feature flags, shouldn't be removed, helpful for debugging/maintenance reasons
    BILLING_FORECASTING_ISSUES: 'billing-forecasting-issues', // owner: #team-billing, see `Billing.tsx`, used to raise a warning when billing is having problems
    HOG: 'hog', // owner: #team-data-tools, see `DebugScene.tsx` and also insights
    NAV_PANEL_CAMPAIGN: 'nav-panel-campaign', // owner: #team-growth, sidebar promotional campaign, payload-driven. See NavPanelAdvertisement.tsx
    QUERY_TIMINGS: 'query-timings', // owner: #team-analytics-platform, usage: see `dataTableLogic.ts`
    REDIRECT_SIGNUPS_TO_INSTANCE: 'redirect-signups-to-instance', // owner: @raquelmsmith, see `signupLogic.ts`
    SESSION_RESET_ON_LOAD: 'session-reset-on-load', // owner: @benjackwhite, usage: see `loadPosthogJS.tsx`
    SETTINGS_PERSONS_ON_EVENTS_HIDDEN: 'settings-persons-on-events-hidden', // owner: #team-platform-features, see `SettingsMap.tsx`
    SUPPORT_MESSAGE_OVERRIDE: 'support-message-override', // owner: #team-support, see `SidePanelSupport.tsx`
    THEME_OVERRIDE: 'theme', // owner: @aprilfools, see `themeLogic.ts`
    USAGE_SPEND_DASHBOARDS: 'usage-spend-dashboards', // owner: #team-billing, see `Billing.tsx`, needed to exclude orgs with more than 100 teams

    // Holidays overrides, will be around forever
    CHRISTMAS_OVERRIDE: 'christmas-override', // owner: #team-growth, overrides the checks for Christmas to return true when this is enabled
    HALLOWEEN_OVERRIDE: 'halloween-override', // owner: #team-growth, overrides the checks for Halloween to return true when this is enabled

    // UX flags, used to control the UX of the app
    AI_FIRST: 'ai-first', // this a larger change, not released to team yet

    // Feature flags used to control opt-in for different behaviors, should not be removed
    AUDIT_LOGS_ACCESS: 'audit-logs-access', // owner: #team-platform-features, used to control access to audit logs
    BATCH_EXPORT_EARLIEST_BACKFILL: 'batch-export-earliest-backfill', // owner: #team-batch-exports, allow backfilling from beginning of time
    CONTROL_SUPPORT_LOGIN: 'control_support_login', // owner: #team-security, used to control whether users can opt out of support impersonation
    CUSTOM_CSS_THEMES: 'custom-css-themes', // owner: #team-growth, used to enable custom CSS for teams who want to have fun
    GAME_CENTER: 'game-center', // owner: everybody, this is just internal for now
    HEDGEHOG_SKIN_SPIDERHOG: 'hedgehog-skin-spiderhog', // owner: #team-web-analytics, used to reward beta users for web analytics
    HIGH_FREQUENCY_BATCH_EXPORTS: 'high-frequency-batch-exports', // owner: #team-batch-exports, allow batch exports to be run every 5min/15min
    METALYTICS: 'metalytics', // owner: #team-platform-features, used to allow companies to see (meta) analytics on access to a specific page
    PERSON_PROPERTY_INCIDENT_ANNOTATION_JAN_2026: 'person-property-incident-annotation-jan-2026', // owner: #team-platform-features, shows system annotation for Jan 6-7 2026 person property incident
    REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU: 'replay-exclude-from-hide-recordings-menu', // owner: #team-replay, used to exclude what other people are seeing in Replay
    SHOW_UPGRADE_TO_MANAGED_ACCOUNT: 'show-upgrade-to-managed-account', // owner: #team-billing, used to give free accounts a way to force upgrade to managed account
    WEBHOOKS_DENYLIST: 'webhooks-denylist', // owner: #team-ingestion, used to disable webhooks for certain companies

    // Legacy flags, TBD if they need to be removed
    BATCH_EXPORTS_POSTHOG_HTTP: 'posthog-http-batch-exports', // owner: #team-batch-exports
    BILLING_SKIP_FORECASTING: 'billing-skip-forecasting', // owner: @zach
    BOX_PLOT_INSIGHT: 'box-plot-insight', // owner: @pauldambra #team-product-analytics
    CALENDAR_HEATMAP_INSIGHT: 'calendar-heatmap-insight', // owner: @jabahamondes #team-web-analytics
    COOKIELESS_SERVER_HASH_MODE_SETTING: 'cookieless-server-hash-mode-setting', // owner: #team-web-analytics
    CSP_REPORTING: 'mexicspo', // owner @pauldambra @lricoy @robbiec
    ERROR_TRACKING_ALERT_ROUTING: 'error-tracking-alert-routing', // owner: #team-error-tracking
    EXPERIMENT_INTERVAL_TIMESERIES: 'experiments-interval-timeseries', // owner: @jurajmajerik #team-experiments
    /* The below flag is used to activate unmounting charts outside the viewport, as we're currently investigating frontend performance
    issues related to this and want to know the impact of having it on vs. off. */
    EXPERIMENTAL_DASHBOARD_ITEM_RENDERING: 'experimental-dashboard-item-rendering', // owner: @thmsobrmlr #team-product-analytics
    GATEWAY_PERSONAL_API_KEY: 'gateway-personal-api-key', // owner: #team-platform-features
    IMPROVED_COOKIELESS_MODE: 'improved-cookieless-mode', // owner: #team-web-analytics
    LINEAGE_DEPENDENCY_VIEW: 'lineage-dependency-view', // owner: #team-data-modeling
    MEMBERS_CAN_USE_PERSONAL_API_KEYS: 'members-can-use-personal-api-keys', // owner: @yasen-posthog #team-platform-features
    PERSONLESS_EVENTS_NOT_SUPPORTED: 'personless-events-not-supported', // owner: #team-analytics-platform
    QUERY_RUNNING_TIME: 'query_running_time', // owner: #team-analytics-platform
    REPLAY_HOGQL_FILTERS: 'replay-hogql-filters', // owner: @pauldambra #team-replay
    REPLAY_SETTINGS_HELP: 'replay-settings-help', // owner: @veryayskiy #team-replay
    REPLAY_TRIGGER_TYPE_CHOICE: 'replay-trigger-type-choice', // owner: @pauldambra #team-replay
    SESSION_REPLAY_BACKEND_LOGS: 'session-replay-backend-logs', // owner: #team-replay
    SESSION_REPLAY_DOCTOR: 'session-replay-doctor', // owner: #team-replay
    SETTINGS_BOUNCE_RATE_PAGE_VIEW_MODE: 'settings-bounce-rate-page-view-mode', // owner: #team-web-analytics
    SETTINGS_PERSONS_JOIN_MODE: 'settings-persons-join-mode', // owner: #team-analytics-platform
    SETTINGS_SESSION_TABLE_VERSION: 'settings-session-table-version', // owner: #team-analytics-platform
    SETTINGS_SESSIONS_V2_JOIN: 'settings-sessions-v2-join', // owner: @robbie-c #team-web-analytics
    SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES: 'web-analytics-pre-aggregated-tables', // owner: @lricoy #team-web-analytics
    STARTUP_PROGRAM_INTENT: 'startup-program-intent', // owner: @pawel-cebula #team-billing
    SURVEYS_ACTIONS: 'surveys-actions', // owner: #team-surveys
    SURVEYS_ADAPTIVE_LIMITS: 'surveys-adaptive-limits', // owner: #team-surveys
    SURVEYS_TRANSLATIONS: 'surveys-translations', // owner: #team-surveys
    SURVEYS_AI_FIRST_EMPTY_STATE: 'surveys-ai-first-empty-state', // owner: #team-surveys, enables ai-first empty state
    SURVEYS_REDESIGNED_VIEW: 'surveys-redesigned-view', // owner: #team-surveys, enables the redesigned survey view with sidebar
    TRACK_DETACHED_ELEMENTS: 'track-detached-elements', // owner: @pauldambra #team-replay
    TRACK_MEMORY_USAGE: 'track-memory-usage', // owner: @pauldambra #team-replay
    TRACK_REACT_FRAMERATE: 'track-react-framerate', // owner: @pauldambra #team-replay
    WEB_ANALYTICS_API: 'web-analytics-api', // owner: #team-web-analytics
    WEB_ANALYTICS_FOR_MOBILE: 'web-analytics-for-mobile', // owner: #team-web-analytics
    WEB_ANALYTICS_REFERRER_URL_DRILLDOWN: 'web-analytics-referrer-url-drilldown', // owner: @jabahamondes #team-web-analytics
    WEB_EXPERIMENTS: 'web-experiments', // owner: #team-experiments

    // Temporary feature flags, still WIP, should be removed eventually
    AA_TEST_BAYESIAN_LEGACY: 'aa-test-bayesian-legacy', // owner: #team-experiments
    AA_TEST_BAYESIAN_NEW: 'aa-test-bayesian-new', // owner: #team-experiments
    ACTION_REFERENCE_COUNT: 'action-reference-count', // owner: @andyzzhao #team-product-analytics, gates bulk action reference counting on actions list
    ADVANCE_MARKETING_ANALYTICS_SETTINGS: 'advance-marketing-analytics-settings', // owner: @jabahamondes  #team-web-analytics
    AI_EVENTS_TABLE_ROLLOUT: 'ai-events-table-rollout', // owner: #team-llm-analytics, gates reads off the dedicated ai_events table
    AI_ONLY_MODE: 'ai-only-mode', // owner: #team-posthog-ai
    ALERTS_ANOMALY_DETECTION: 'alerts-anomaly-detection', // owner: @andrewm4894
    /** Alert edit modal: check history chart + chart/table toggle (table remains when off). */
    ALERTS_HISTORY_CHART: 'alerts-history-chart', // owner: #team-analytics-platform
    ALERTS_INLINE_NOTIFICATIONS: 'alerts-inline-notifications', // owner: @vdekrijger
    ALERTS_INVESTIGATION_AGENT: 'alerts-investigation-agent', // owner: @andrewm4894, anomaly alerts — investigation agent on firing
    /** Insight alert quiet hours (schedule restriction UI; backend field is always honored when set). */
    ALERTS_QUIET_HOURS: 'alerts-quiet-hours', // owner: @mattp, #team-analytics-platform
    AMPLITUDE_BATCH_IMPORT_OPTIONS: 'amplitude-batch-import-options', // owner: #team-ingestion
    APPROVALS: 'approvals', // owner: @yasen-posthog #team-platform-features
    AVERAGE_PAGE_VIEW_COLUMN: 'average-page-view-column', // owner: @jordanm-posthog #team-web-analytics
    BACKFILL_WORKFLOWS_DESTINATION: 'backfill-workflows-destination', // owner: #team-batch-exports
    BATCH_EXPORTS_BIGQUERY_INTEGRATION: 'batch-exports-bigquery-integration', // owner: @tomasfarias #team-batch-exports
    BING_ADS_SOURCE: 'bing-ads-source', // owner: @jabahamondes #team-web-analytics
    CDP_ACTIVITY_LOG_NOTIFICATIONS: 'cdp-activity-log-notifications', // owner: #team-workflows-cdp
    CDP_DWH_TABLE_SOURCE: 'cdp-dwh-table-source', // owner: #team-workflows-cdp
    CDP_HOG_SOURCES: 'cdp-hog-sources', // owner #team-workflows-cdp
    CDP_NEW_PRICING: 'cdp-new-pricing', // owner: #team-workflows
    CDP_PERSON_UPDATES: 'cdp-person-updates', // owner: #team-workflows-cdp
    CDP_VERCEL_LOG_DRAIN: 'cdp-vercel-log-drain', // owner: #team-workflows-cdp
    COHORT_CALCULATION_HISTORY: 'cohort-calculation-history', // owner: @gustavo #team-feature-flags
    COHORT_EMAIL_LOOKUP_CLICKHOUSE: 'cohort-email-lookup-clickhouse', // owner: @gustavo #team-feature-flags
    COHORT_INLINE_CALCULATION: 'inline-cohort-calculation', // owner: #team-analytics-platform, inlines fast dynamic cohort queries instead of using precomputed cohortpeople table
    CONDENSED_FILTER_BAR: 'condensed_filter_bar', // owner: @jordanm-posthog #team-web-analytics
    CREATE_FORM_TOOL: 'phai-create-form-tool', // owner: @kappa90 #team-posthog-ai
    CRM_ITERATION_ONE: 'crm-iteration-one', // owner: @arthurdedeus #team-customer-analytics
    CUSTOM_PRODUCTS_SIDEBAR: 'custom-products-sidebar', // owner: @rafaeelaudibert #team-growth
    CUSTOMER_ANALYTICS: 'customer-analytics-roadmap', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_ANALYTICS_JOURNEYS: 'customer-analytics-journeys', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_DASHBOARD_TEMPLATE_AUTHORING: 'customer-dashboard-template-authoring', // owner: @mattp #team-analytics-platform org-scoped; project templates for non-staff
    CUSTOMER_PROFILE_CONFIG_BUTTON: 'customer-profile-config-button', // owner: @arthurdedeus #team-customer-analytics
    DASHBOARD_AUTO_PREVIEW_LIMIT: 'dashboard-auto-preview-limit', // owner: @pauldambra #team-product-analytics
    DASHBOARD_QUICK_FILTERS_EXPERIMENT: 'dashboard-quick-filters-experiment', // owner: @vdekrijger #team-product-analytics multivariate=control,test
    DASHBOARD_TEMPLATE_CHOOSER_EXPERIMENT: 'dashboard-template-chooser-experiment', // owner: @mattp #team-analytics-platform multivariate=control,simple,new
    DATA_MODELING_BACKEND_V2: 'data-modeling-backend-v2', // owner: #team-data-modeling
    DATA_MODELING_MULTI_DAG: 'data-modeling-multi-dag', // owner: #team-data-modeling
    DATA_MODELING_TAB: 'data-modeling-tab', // owner: #team-data-modeling
    DATA_WAREHOUSE_SCENE: 'data-warehouse-scene', // owner: #team-data-modeling
    DEFAULT_EVALUATION_ENVIRONMENTS: 'default-evaluation-environments', // owner: @dmarticus #team-feature-flags
    DROP_PERSON_LIST_ORDER_BY: 'drop-person-list-order-by', // owner: @arthurdedeus #team-customer-analytics
    DWH_FREE_SYNCS: 'dwh-free-syncs', // owner: @Gilbert09  #team-warehouse-sources
    DWH_JOIN_TABLE_PREVIEW: 'dwh-join-table-preview', // owner: @arthurdedeus #team-customer-analytics
    DWH_POSTGRES_CDC: 'dwh-postgres-cdc', // owner: #team-warehouse-sources
    DWH_POSTGRES_DIRECT_QUERY: 'dwh-postgres-direct-query', // owner: #team-data-tools
    EDITOR_DRAFTS: 'editor-drafts', // owner: @EDsCODE #team-data-tools
    ENDPOINTS: 'embedded-analytics', // owner: @sakce #team-clickhouse
    ERROR_TRACKING_ALERTS_WIZARD: 'error-tracking-alerts-wizard', // owner: @aleks #team-error-tracking
    ERROR_TRACKING_FORCE_QUERY_V2: 'error-tracking-force-query-v2', // owner: #team-error-tracking
    ERROR_TRACKING_FORCE_QUERY_V3: 'error-tracking-force-query-v3', // owner: #team-error-tracking
    ERROR_TRACKING_INGESTION_CONTROLS: 'error-tracking-ingestion-controls', // owner: #team-error-tracking
    ERROR_TRACKING_INSIGHTS: 'error-tracking-insights', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_ISSUE_CORRELATION: 'error-tracking-issue-correlation', // owner: @david #team-error-tracking
    ERROR_TRACKING_ISSUE_SPLITTING: 'error-tracking-issue-splitting', // owner: @david #team-error-tracking
    ERROR_TRACKING_JIRA_INTEGRATION: 'error-tracking-jira-integration', // owner: #team-error-tracking
    ERROR_TRACKING_QUERY_V2: 'error-tracking-query-v2', // owner: #team-error-tracking
    ERROR_TRACKING_QUERY_V3: 'error-tracking-query-v3', // owner: #team-error-tracking
    ERROR_TRACKING_RECOMMENDATIONS: 'error-tracking-recommendations', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_RELATED_ISSUES: 'error-tracking-related-issues', // owner: #team-error-tracking
    ERROR_TRACKING_REVENUE_SORTING: 'error-tracking-revenue-sorting', // owner: @david #team-error-tracking
    ERROR_TRACKING_SETTINGS_SPLIT: 'error-tracking-settings-split', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_SPIKE_ALERTING: 'error-tracking-spike-alerting', // owner: #team-error-tracking
    ERROR_TRACKING_WEEKLY_DIGEST: 'error-tracking-weekly-digest', // owner: #team-error-tracking
    EVENT_MEDIA_PREVIEWS: 'event-media-previews', // owner: @alexlider
    EXPERIMENT_AI_ANALYSIS_TAB: 'experiment-ai-analysis-tab', // owner: @rodrigoi #team-experiments
    EXPERIMENT_FUNNEL_ACTORS_QUERY: 'experiment-funnel-actors-query', // owner: @rodrigoi #team-experiments
    EXPERIMENT_FUNNEL_DWH_SUPPORT: 'experiment-funnel-dwh-support', // owner: @rodrigoi #team-experiments
    EXPERIMENT_QUERY_PREAGGREGATION: 'experiment-query-preaggregation', // owner: @jurajmajerik #team-experiments
    EXPERIMENT_SESSION_REPLAYS_SKILL: 'experiment-session-replays-skill', // owner: @rodrigoi #team-experiments
    EXPERIMENT_SIGNIFICANCE_ALERTS: 'experiment-significance-alerts', // owner: @jurajmajerik #team-experiments
    EXPERIMENTS_DW_AA_TEST: 'experiments-dw-aa-test', // owner: @rodrigoi #team-experiments
    EXPERIMENTS_MATURED_USERS_FILTER: 'experiments-matured-users-filter', // owner: @jurajmajerik #team-experiments
    EXPERIMENTS_SAMPLE_RATIO_MISMATCH: 'experiments-sample-ratio-mismatch', // owner: @jurajmajerik #team-experiments
    EXPERIMENTS_SHOW_SQL: 'experiments-show-sql', // owner: @jurajmajerik #team-experiments
    EXPERIMENTS_SYNC_QUERIES: 'experiments-sync-queries', // owner: @andehen #team-experiments
    EXPERIMENTS_TEMPLATES: 'experiments-templates', // owner: @rodrigoi #team-experiments
    FEATURE_FLAG_COHORT_CREATION: 'feature-flag-cohort-creation', // owner: #team-feature-flags
    FEATURE_FLAG_CREATION_INTENTS: 'feature-flag-creation-intents', // owner: #team-feature-flags
    FEATURE_FLAG_DRAG_DROP_CONDITIONS: 'feature-flag-drag-drop-conditions', // owner: @gustavo #team-feature-flags
    FEATURE_FLAG_MIXED_TARGETING: 'feature-flag-mixed-targeting', // owner: @dmarticus #team-feature-flags
    FEATURE_FLAG_NOTIFICATIONS: 'feature-flag-notifications', // owner: @reecejones #team-platform-features
    FEATURE_FLAG_USAGE_DASHBOARD_CHECKBOX: 'feature-flag-usage-dashboard-checkbox', // owner: #team-feature-flags, globally disabled, enables opt-out of auto dashboard creation
    FEATURE_FLAGS_ACROSS_PROJECTS_INDEX: 'feature-flags-across-projects-index', // owner: #team-platform-features
    FEATURE_FLAGS_V2: 'feature-flags-v2', // owner: @dmarticus #team-feature-flags
    FLAG_BUCKETING_IDENTIFIER: 'flag-bucketing-identifier', // owner: @andehen #team-experiments
    FLAG_EVALUATION_RUNTIMES: 'flag-evaluation-runtimes', // owner: @dmarticus #team-feature-flags
    FLAG_EVALUATION_TAGS: 'flag-evaluation-tags', // owner: @dmarticus #team-feature-flags
    FLAGGED_FEATURE_INDICATOR: 'flagged-feature-indicator', // owner: @benjackwhite
    GROUP_PROFILE_EXPERIMENT: 'group-profile-experiment', // owner: @arthurdedeus #team-customer-analytics
    HACKATHONS_SUBSCRIPTIONS: 'hackathons_subscriptions', // owner: #team-analytics-platform, gates listing subscription delivery history and AI change summaries
    INTER_PROJECT_TRANSFERS: 'inter-project-transfers', // owner: @reecejones #team-platform-features
    JS_SNIPPET_VERSIONING: 'js-snippet-versioning', // owner: #team-client-libraries
    LEGAL_DOCUMENTS: 'legal-documents', // owner: @rafaeelaudibert #team-growth
    LINKS: 'links', // owner: @marconlp #team-link (team doesn't exist for now, maybe will come back in the future)
    LIVE_DEBUGGER: 'live-debugger', // owner: @marcecoll
    LIVESTREAM_TUI: 'livestream-tui', // owner: @rafaeelaudibert #team-growth
    LLM_ANALYTICS_CLUSTERING_ADMIN: 'llm-analytics-clustering-admin', // owner: #team-llm-analytics
    LLM_ANALYTICS_CLUSTERS_TAB: 'llm-analytics-clusters-tab', // owner: #team-llm-analytics
    LLM_ANALYTICS_DATASETS: 'llm-analytics-datasets', // owner: #team-llm-analytics #team-posthog-ai
    LLM_ANALYTICS_DISCUSSIONS: 'llm-analytics-discussions', // owner: #team-llm-analytics
    LLM_ANALYTICS_EARLY_ADOPTERS: 'llm-analytics-early-adopters', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS: 'llm-analytics-evaluations', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS_CLUSTERING: 'llm-analytics-evaluations-clustering', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS_CUSTOM_MODELS: 'llm-analytics-evaluations-custom-models', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS_HOG_CODE: 'llm-analytics-evaluations-hog-code', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS_REPORTS: 'llm-analytics-evaluations-reports', // owner: #team-llm-analytics
    LLM_ANALYTICS_EVALUATIONS_SUMMARY: 'llm-analytics-evaluations-summary', // owner: #team-llm-analytics
    LLM_ANALYTICS_OFFLINE_EVALS: 'llm-analytics-offline-evals', // owner: #team-llm-analytics
    LLM_ANALYTICS_SENTIMENT: 'llm-analytics-sentiment', // owner: #team-llm-analytics
    LLM_ANALYTICS_SENTIMENT_TAB: 'llm-analytics-sentiment-tab', // owner: #team-llm-analytics
    LLM_ANALYTICS_SESSION_SUMMARIZATION: 'llm-analytics-session-summarization', // owner: #team-llm-analytics
    LLM_ANALYTICS_SESSIONS_VIEW: 'llm-analytics-sessions-view', // owner: #team-llm-analytics
    LLM_ANALYTICS_SKILLS: 'llm-analytics-skills', // owner: #team-llm-analytics
    LLM_ANALYTICS_SUMMARIZATION: 'llm-analytics-summarization', // owner: #team-llm-analytics
    LLM_ANALYTICS_TEXT_VIEW: 'llm-analytics-text-view', // owner: #team-llm-analytics
    LLM_ANALYTICS_TOOLS_CHARTS: 'llm-analytics-tools-charts', // owner: #team-llm-analytics
    LLM_ANALYTICS_TOOLS_TAB: 'llm-analytics-tools-tab', // owner: #team-llm-analytics
    LLM_ANALYTICS_TRACE_NAVIGATION: 'llm-analytics-trace-navigation', // owner: #team-llm-analytics
    LLM_ANALYTICS_TRACE_REVIEW: 'llma-trace-review', // owner: #team-llm-analytics
    LLM_ANALYTICS_TRANSLATION: 'llm-analytics-translation', // owner: #team-llm-analytics
    LLM_ANALYTICS_USER_FEEDBACK: 'llm-analytics-user-feedback', // owner: @adboio #team-surveys
    LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT: 'llm-observability-show-input-output', // owner: #team-llm-analytics
    LOGS: 'logs', // owner: #team-logs
    LOGS_ALERTING: 'logs-alerting', // owner: #team-logs
    LOGS_SAVED_VIEWS: 'logs-saved-views', // owner: #team-logs
    LOGS_SERVICES_VIEW: 'logs-services-view', // owner: #team-logs
    LOGS_SETTINGS: 'logs-settings', // owner: #team-logs
    LOGS_SETTINGS_JSON: 'logs-settings-json', // owner: #team-logs
    LOGS_SETTINGS_PII_SCRUB: 'logs-settings-pii-scrub', // owner: #team-logs
    LOGS_SETTINGS_RETENTION: 'logs-settings-retention', // owner: #team-logs
    LOGS_SPARKLINE_SERVICE_BREAKDOWN: 'logs-sparkline-service-breakdown', // owner: #team-logs
    LOGS_TABBED_VIEW: 'logs-tabbed-view', // owner: #team-logs
    MANAGED_VIEWSETS: 'managed-viewsets', // owner: @rafaeelaudibert #team-revenue-analytics
    MARKETING_ANALYTICS_DRILL_DOWN: 'marketing-analytics-drill-down', // owner: @jabahamondes  #team-web-analytics
    MARKETING_ANALYTICS_EXTENDED_DRILL_DOWN: 'marketing-analytics-extended-drill-down', // owner: @jabahamondes  #team-web-analytics
    MARKETING_ANALYTICS_MULTI_TOUCH_ATTRIBUTION: 'marketing-analytics-multi-touch-attribution', // owner: @jabahamondes #team-web-analytics
    MARKETING_ANALYTICS_UTM_AUDIT: 'marketing-analytics-utm-audit', // owner: @jabahamondes  #team-web-analytics
    MAX_AI_INSIGHT_SEARCH: 'max-ai-insight-search', // owner: #team-posthog-ai
    MAX_BILLING_CONTEXT: 'max-billing-context', // owner: @pawel-cebula #team-billing
    MAX_DEEP_RESEARCH: 'max-deep-research', // owner: @kappa90 #team-posthog-ai
    MCP_SERVERS: 'mcp-servers', // owner: #team-posthog-ai
    MESSAGING_SES: 'messaging-ses', // owner #team-workflows
    METRICS: 'metrics', // owner: #team-apm (@jonmcwest, @frankh)
    NEW_LOGS_DATE_RANGE_PICKER: 'new-logs-date-range-picker', // owner: #team-logs
    NEW_TAB_PROJECT_EXPLORER: 'new-tab-project-explorer', // owner: #team-platform-ux
    NEW_TEAM_CORE_EVENTS: 'new-team-core-events', // owner: @jabahamondes #team-web-analytics
    NOTEBOOK_PYTHON: 'notebook-python', // owner: #team-data-tools
    NOTEBOOKS_COLLABORATION: 'notebooks-collaboration', // owner: #team-platform-features
    NOTEBOOKS_COLLAPSIBLE_SECTIONS: 'notebooks-collapsible-sections', // owner: @benjackwhite
    ONBOARDING_DATA_WAREHOUSE_VALUE_PROP: 'onboarding-data-warehouse-value-prop', // owner: @fercgomes #team-growth multivariate=control,table,query
    ONBOARDING_HIDE_BREADCRUMBS: 'onboarding-hide-breadcrumbs', // owner: @fercgomes #team-growth, multivariate=true, hides breadcrumbs during onboarding to reduce distractions
    ONBOARDING_MOBILE_INSTALL_HELPER: 'onboarding-mobile-install-helper', // owner: @fercgomes #team-growth multivariate=control,test — target $device_type=Mobile at the flag level
    ONBOARDING_NAVBAR: 'onboarding-navbar', // owner: #team-growth, hides the navbar during onboarding to reduce distractions multivariate=true
    ONBOARDING_PRODUCT_SELECTION_HEADING: 'onboarding-product-selection-heading', // owner: #team-growth, payload overrides the heading copy on the first onboarding page
    ONBOARDING_SESSION_REPLAY_MEDIA: 'onboarding-session-replay-media', // owner: @fercgomes #team-growth multivariate=control,screenshot,demo
    ONBOARDING_SIMPLIFIED_PRODUCT_SELECTION: 'onboarding-simplified-product-selection', // owner: @fercgomes #team-growth multivariate=control,test — DEPRECATED: use PRODUCT_SELECTION_SCREEN_VARIANT
    ONBOARDING_SKIP_INSTALL_STEP: 'onboarding-skip-install-step', // owner: @rafaeelaudibert #team-growth multivariate=true
    ONBOARDING_SOCIAL_PROOF_INFO: 'onboarding-social-proof-info', // owner: @fercgomes #team-growth, payload overrides social proof strings per product
    ONBOARDING_WIZARD_INSTALLATION_IMPROVED_COPY: 'onboarding-wizard-installation-improved-copy', // owner: @fercgomes #team-growth multivariate=control,test
    ONBOARDING_WIZARD_PROMINENCE: 'onboarding-wizard-prominence', // owner: #team-growth multivariate=control,wizard-hero,wizard-tab,wizard-only
    OWNER_ONLY_BILLING: 'owner-only-billing', // owner: @pawelcebula #team-billing
    PAGE_REPORTS_AVERAGE_PAGE_VIEW: 'page-reports-average-page-view', // owner: @jordanm-posthog #team-web-analytics
    PAGE_REPORTS_RANKED_URL_SEARCH: 'page-reports-ranked-url-search', // owner: @jordanm-posthog #team-web-analytics
    PASSKEY_SIGNUP_ENABLED: 'passkey-signup-enabled', // owner: @reecejones #team-platform-features
    PASSWORD_PROTECTED_SHARES: 'password-protected-shares', // owner: @aspicer
    PHAI_PLAN_MODE: 'phai-plan-mode', // owner: #team-posthog-ai
    PHAI_SANDBOX_MODE: 'phai-sandbox-mode', // owner: #team-posthog-ai
    PHAI_TASKS: 'phai-tasks', // owner: #team-array
    PINTEREST_ADS_SOURCE: 'pinterest-ads-source', // owner: @jabahamondes #team-web-analytics
    PIPELINE_STATUS_PAGE: 'pipeline-status-page', // owner: @clr182 #team-support
    POST_ONBOARDING_MODAL_EXPERIMENT: 'post-onboarding-modal-experiment', // owner: @fercgomes #team-growth multivariate=control,test
    POSTHOG_AI_ALERTS: 'posthog-ai-alerts', // owner: #team-posthog-ai
    POSTHOG_AI_BILLING_DISPLAY: 'posthog-ai-billing-display', // owner: #team-posthog-ai
    POSTHOG_AI_CHANGELOG: 'posthog-ai-changelog', // owner: #team-posthog-ai
    POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG: 'posthog-ai-conversation-feedback-config', // owner: #team-posthog-ai
    POSTHOG_AI_CONVERSATION_FEEDBACK_LLMA_SESSIONS: 'posthog-ai-conversation-feedback-llma-sessions', // owner: #team-posthog-ai
    POSTHOG_AI_QUEUE_MESSAGES_SYSTEM: 'posthog-ai-queue-messages-system', // owner: #team-posthog-ai
    POSTHOG_CODE_BILLING: 'posthog-code-billing', // owner: #team-posthog-code
    POSTHOG_CODE_SLACK_AVAILABILITY: 'posthog-code-slack-availability', // owner: #team-posthog-code, gates the PostHog Code Slack integration UI
    PRODUCT_ANALYTICS_AI_INSIGHT_ANALYSIS: 'product-analytics-ai-insight-analysis', // owner: #team-analytics-platform, used to show AI analysis section in insights
    PRODUCT_ANALYTICS_DASHBOARD_AI_ANALYSIS: 'product-analytics-dashboard-ai-analysis', // owner: @anirudhpillai #team-product-analytics
    PRODUCT_ANALYTICS_DASHBOARD_COLORS: 'dashboard-colors', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS: 'product-analytics-dashboard-modal-smart-defaults', // owner: @sam #team-product-analytics
    PRODUCT_ANALYTICS_HIDE_WEEKENDS: 'product-analytics-hide-weekends', // owner: @kliment-slice #team-irl-events
    PRODUCT_ANALYTICS_HOG_CHARTS: 'product-analytics-hog-charts', // owner: @sampennington #team-product-analytics
    PRODUCT_ANALYTICS_HOME_TAB: 'product-analytics-home-tab', // owner: @anirudhpillai #team-product-analytics
    PRODUCT_ANALYTICS_INSIGHT_HORIZONTAL_CONTROLS: 'insight-horizontal-controls', // owner: #team-product-analytics
    PRODUCT_ANALYTICS_PATHS_V2: 'paths-v2', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_ANALYTICS_RETENTION_AGGREGATION: 'retention-aggregation', // owner: @anirudhpillai #team-product-analytics
    PRODUCT_ANALYTICS_RETENTION_DWH: 'retention-dwh', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_AUTONOMY: 'product-autonomy', // owner: #team-signals
    PRODUCT_CONVERSATIONS: 'product-conversations', // owner: @veryayskiy #team-conversations
    PRODUCT_SELECTION_SCREEN_VARIANT: 'product-selection-screen-variant', // owner: @fercgomes #team-growth multivariate=control,spotlight,multiproduct
    PRODUCT_SUPPORT: 'product-support-release', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_AI_SUGGESTION: 'product-support-ai-suggestion', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_EMAIL_CHANNEL: 'product-support-email-channel', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_SIDE_PANEL: 'product-support-side-panel', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_TEAMS_ENABLED: 'product-support-teams-enabled', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_TICKET_VIEWS: 'product-support-ticket-views', // owner: @veryayskiy #team-conversations
    PRODUCT_TOURS: 'product-tours-2025', // owner: @adboio #team-surveys
    PRODUCT_TOURS_LOCALIZATION: 'product-tours-localization', // owner: @adboio #team-surveys
    PROMOTED_EVENT_PROPERTIES_EDIT: 'promoted-event-properties-edit', // owner: @pauldambra #team-product-analytics, gates the promoted-property picker on the event definition edit page
    PROMPT_MANAGEMENT: 'prompt-management', // owner: #team-llm-analytics
    PROVISION_MANAGED_WAREHOUSE_BETA: 'provision-managed-warehouse-beta', // owner: @EDsCODE #team-managed-warehouse
    QUICK_START_PULSE_INDICATOR: 'quick-start-pulse-indicator', // owner: @fercgomes #team-growth multivariate=control,test
    RBAC_UI_REDESIGN: 'rbac-ui-redesign', // owner: @reece #team-platform-features
    REAL_TIME_NOTIFICATIONS: 'real-time-notifications', // owner: #team-platform-features
    REALTIME_COHORT_FLAG_TARGETING: 'realtime-cohort-flag-targeting', // owner: @dmarticus #team-feature-flags
    RECORDINGS_PLAYER_EVENT_PROPERTY_EXPANSION: 'recordings-player-event-property-expansion', // owner: @pauldambra #team-replay
    REMOTE_CONFIG: 'remote-config', // owner: #team-platform-features
    REPLAY_COLLAPSE_INSPECTOR_ITEMS: 'replay-collapse-inspector-items', // owner: @fasyy612 #team-replay
    REPLAY_FILTERS_REDESIGN: 'replay-filters-redesign', // owner: @ksvat #team-replay
    REPLAY_NEW_DETECTED_URL_COLLECTIONS: 'replay-new-detected-url-collections', // owner: @ksvat #team-replay multivariate=true
    REPLAY_TRIGGERS_V2: 'replay-triggers-v2', // owner: #team-replay
    REPLAY_UI_REDESIGN_2026: 'replay-ui-redesign-2026', // owner: #team-replay, New UI layout for replay
    REPLAY_VIDEO_BASED_SUMMARIZATION: 'replay-video-based-summarization', // owner: #team-replay
    REPLAY_WAIT_FOR_IFRAME_READY: 'replay-wait-for-full-snapshot-playback', // owner: @ksvat #team-replay
    REPLAY_X_LLM_ANALYTICS_CONVERSATION_VIEW: 'replay-x-llm-analytics-conversation-view', // owner: @pauldambra #team-replay
    REVENUE_ANALYTICS: 'revenue-analytics', // owner: @rafaeelaudibert #team-customer-analytics
    REVENUE_FIELDS_IN_POWER_USERS_TABLE: 'revenue-fields-in-power-users-table', // owner: @arthurdedeus #team-customer-analytics
    SCHEDULE_FEATURE_FLAG_VARIANTS_UPDATE: 'schedule-feature-flag-variants-update', // owner: @gustavo #team-feature-flags
    SCHEMA_ENFORCEMENT_REJECT: 'schema-enforcement-reject', // owner: @aspicer, gates the ability to set schema enforcement mode to "reject"
    SCHEMA_MANAGEMENT: 'schema-management', // owner: @aspicer
    SEARCH_DEBOUNCE_ALL: 'search-debounce-all', // owner: @adamleithp #team-platform-ux
    SEARCH_RE_RANK: 'search-re-rank', // owner: @adamleithp #team-platform-ux
    SEEKBAR_PREVIEW_SCRUBBING: 'seekbar-preview-scrubbing', // owner: @pauldambra #team-replay
    SEMVER_TARGETING: 'semver-targeting', // owner: #team-feature-flags
    SHOPIFY_DWH: 'shopify-dwh', // owner: #team-warehouse-sources
    SHOW_DATA_PIPELINES_NAV_ITEM: 'show-data-pipelines-nav-item', // owner: @raquelmsmith
    SHOW_REFERRER_FAVICON: 'show-referrer-favicon', // owner: @jordanm-posthog #team-web-analytics
    SHOW_REPLAY_FILTERS_FEEDBACK_BUTTON: 'show-replay-filters-feedback-button', // owner: @ksvat #team-replay
    SIGNUP_AA_TEST: 'signup-aa-test', // owner: @andehen #team-experiments multivariate=control,test
    SLACK_DWH: 'slack-dwh', // owner: @MarconLP #team-warehouse-sources
    SNAPCHAT_ADS_SOURCE: 'snapchat-ads-source', // owner: @jabahamondes #team-web-analytics
    SQL_EDITOR_VIM_MODE: 'sql-editor-vim-mode', // owner: @arthurdedeus
    SSE_DASHBOARDS: 'sse-dashboards', // owner: @aspicer #team-analytics-platform
    SUBSCRIPTION_AI_SUMMARY_PROMPT_GUIDE: 'subscription-ai-summary-prompt-guide', // owner: #team-analytics-platform, gates the per-subscription prompt guide textarea
    SURVEY_HEADLINE_SUMMARY: 'survey-headline-summary', // owner: @adboio #team-surveys
    SURVEYS_ERROR_TRACKING_CROSS_SELL: 'surveys-in-error-tracking', // owner: @adboio #team-surveys
    SURVEYS_FORM_BUILDER: 'surveys-form-builder', // owner: @adboio #team-surveys
    SURVEYS_INSIGHT_BUTTON_EXPERIMENT: 'ask-users-why-ai-vs-quickcreate', // owner: @adboio #team-surveys multivariate=true
    SURVEYS_TOOLBAR: 'surveys-toolbar', // owner: @fcgomes
    SURVEYS_WEB_ANALYTICS_CROSS_SELL: 'surveys-in-web-analytics', // owner: @adboio #team-surveys
    TASK_SUMMARIES: 'task-summaries', // owner: #team-llm-analytics
    TASK_TOOL: 'phai-task-tool', // owner: @kappa90 #team-posthog-ai
    TASKS: 'tasks', // owner: #team-llm-analytics
    TAXONOMIC_FILTER_CATEGORY_DROPDOWN: 'taxonomic-filter-category-dropdown', // owner: @pauldambra #team-product-analytics multivariate=control,pill,icon
    TOGGLE_PROPERTY_ARRAYS: 'toggle-property-arrays', // owner: @arthurdedeus #team-customer-analytics
    TRACING: 'tracing', // owner: #team-apm (@jonmcwest, @frankh)
    TRAFFIC_TYPE_VIRTUAL_PROPERTIES: 'traffic-type-virtual-properties', // owner: #team-web-analytics
    UNIFIED_HEALTH_PAGE: 'unified-health-page', // owner: @jordanm-posthog #team-web-analytics
    USER_INTERVIEWS: 'user-interviews', // owner: @Twixes @jurajmajerik
    UX_REMOVE_SIDEPANEL: 'ux-remove-sidepanel', // owner: #team-surveys
    VISUAL_REVIEW: 'visual-review', // owner: #team-devex
    WAREHOUSE_SOURCE_WEBHOOKS: 'warehouse-source-webhooks', // owner: #team-warehouse-sources @Gilbert09
    WEB_ANALYTICS_BOT_ANALYSIS: 'web-analytics-bot-analysis', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_CONVERSION_GOAL_PREAGG: 'web-analytics-conversion-goal-preagg', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_DRAG_TO_ZOOM: 'web-analytics-drag-to-zoom', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_EMPTY_ONBOARDING: 'web-analytics-empty-onboarding', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_FILTERS_V2: 'web-analytics-filters-v2', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_HEALTH_TAB: 'web_analytics_health_tab', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_INCLUDE_HOST: 'web-analytics-include-host', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_LIVE_DOMAIN_FILTER: 'web-analytics-live-domain-filter', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_LIVE_EDIT_LAYOUT: 'web-analytics-live-edit-layout', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_LIVE_MAP: 'web-analytics-live-map', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_LIVE_METRICS: 'web-analytics-live-metrics', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_LIVE_REFERRERS: 'web-analytics-live-referrers', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_MARKETING: 'marketing-analytics', // owner: @jabahamondes #team-web-analytics
    WEB_ANALYTICS_OPEN_URL: 'web-analytics-open-url', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_REGIONS_MAP: 'web-analytics-regions-map', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_SESSION_PROPERTY_CHARTS: 'web-analytics-session-property-charts', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_TILE_TOGGLES: 'web-analytics-tile-toggles', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_TOOLTIP_COMPARISON_LABELS: 'web-analytics-tooltip-comparison-labels', // owner: @lricoy #team-web-analytics
    WORKFLOWS_BATCH_TRIGGERS: 'workflows-batch-triggers', // owner: #team-workflows
    WORKFLOWS_INTERNAL_EVENT_FILTERS: 'workflows-internal-event-filters', // owner: @haven #team-workflows
    WORKFLOWS_PERSON_TIMEZONE: 'workflows-person-timezone', // owner: #team-workflows
    WORKFLOWS_PUSH_NOTIFICATIONS: 'workflows-push-notifications', // owner: @Odin #team-workflows
    WORKFLOWS_RECURRING_SCHEDULES: 'workflows-recurring-schedules', // owner: #team-workflows
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
export const SESSION_SUMMARY_FEEDBACK_SURVEY_ID = '019d4ecc-4ec5-0000-6b47-6a75b18bfd2b'

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

export const LOGS_ALERT_FIRING_SUB_TEMPLATE_ID = 'logs-alert-firing'
export const LOGS_ALERT_FIRING_EVENT_ID = '$logs_alert_firing'
export const LOGS_ALERT_RESOLVED_EVENT_ID = '$logs_alert_resolved'
export const LOGS_ALERT_AUTO_DISABLED_EVENT_ID = '$logs_alert_auto_disabled'

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
    [SDKKey.REACT_ROUTER]: 'javascript',
    [SDKKey.REMIX]: 'javascript',
    [SDKKey.SVELTE]: 'javascript',
    [SDKKey.VUE_JS]: 'javascript',
    [SDKKey.WEBFLOW]: 'javascript',
    [SDKKey.API]: 'javascript',
    [SDKKey.TANSTACK_START]: 'react',
    [SDKKey.VITE]: 'react',
}
