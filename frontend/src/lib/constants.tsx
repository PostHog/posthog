import type { LemonSelectOptions } from '@posthog/lemon-ui'

import { ChartDisplayCategory, ChartDisplayType, Region, SDKKey, type SSOProvider } from '../types'

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
    [ChartDisplayType.Metric]: ChartDisplayCategory.TimeSeries,
    [ChartDisplayType.ActionsPie]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsBarValue]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.ActionsTable]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.WorldMap]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.CalendarHeatmap]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.TwoDimensionalHeatmap]: ChartDisplayCategory.TotalValue,
    [ChartDisplayType.BoxPlot]: ChartDisplayCategory.TimeSeries,
    // The slope's two points are the first and last interval bucket, so it's time-series at heart;
    // it keeps the group-by interval and InsightDisplayConfig hides the options between the ends.
    [ChartDisplayType.SlopeGraph]: ChartDisplayCategory.TimeSeries,
}
export const NON_TIME_SERIES_DISPLAY_TYPES = Object.entries(DISPLAY_TYPES_TO_CATEGORIES)
    .filter(([, category]) => category === ChartDisplayCategory.TotalValue)
    .map(([displayType]) => displayType as ChartDisplayType)

/** Display types for which `breakdown` is hidden and ignored. Sync with backend NON_BREAKDOWN_DISPLAY_TYPES. */
export const NON_BREAKDOWN_DISPLAY_TYPES = [
    ChartDisplayType.BoldNumber,
    ChartDisplayType.Metric,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.TwoDimensionalHeatmap,
    ChartDisplayType.BoxPlot,
]
/** Display types which only work with a single series. */
export const SINGLE_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.Metric,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.TwoDimensionalHeatmap,
]

export const NON_VALUES_ON_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.ActionsTable,
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
    ChartDisplayType.Metric,
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
export const STALE_EVENT_DAYS = 30
export const STALE_EVENT_SECONDS = STALE_EVENT_DAYS * 24 * 60 * 60

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
    CREATE_BUTTON_NAV_EXPERIMENT: 'create-button-nav-experiment', // owner: #team-platform-ux multivariate=control,test — adds a Create dropdown to the top of the Browse tab in the left nav
    MORE_MENU_ICON_EXPERIMENT: 'more-menu-icon-experiment', // owner: #team-platform-ux multivariate=control,test — A/B test of the "More" nav button icon: control = 3-line hamburger menu icon, test = filled burger glyph
    STARRED_REORDER: 'starred-reorder', // owner: #team-platform-ux, drag-and-drop reorder of starred shortcuts in the side panel
    UX_HIDE_PROJECT_NOTICE: 'ux-hide-project-notice', // owner: #team-platform-ux, hides the project notice banner across all scenes

    // Feature flags used to control opt-in for different behaviors, should not be removed
    AGENT_PLATFORM: 'agent-platform', // owner: @benwhite #team-agents, gates the agent-platform surface — MCP tools + the PostHog Code agents view (hidden until GA; product DB is dev-only)
    AI_TRAINING: 'ai-training', // owner: @nicowaltz #team-replay #ai-research, gates the AI training opt-out UI and API enforcement
    AUDIT_LOGS_ACCESS: 'audit-logs-access', // owner: #team-platform-features, used to control access to audit logs
    AUTH_FLOW_VARIANT: 'auth-flow-variant', // owner: @fercgomes #team-growth multivariate=legacy,paper-desk — selects the auth flow experience (login, signup, invited signup, email verification); paper-desk is the new design, legacy is the existing design
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
    EXPERIMENT_INTERVAL_TIMESERIES: 'experiments-interval-timeseries', // owner: @jurajmajerik #team-experiments
    /* The below flag is used to activate unmounting charts outside the viewport, as we're currently investigating frontend performance
    issues related to this and want to know the impact of having it on vs. off. */
    EXPERIMENTAL_DASHBOARD_ITEM_RENDERING: 'experimental-dashboard-item-rendering', // owner: @thmsobrmlr #team-product-analytics
    GATEWAY_PERSONAL_API_KEY: 'gateway-personal-api-key', // owner: #team-platform-features
    HEATMAPS_COHORT_FILTER: 'heatmaps-cohort-filter', // owner: #team-web-analytics
    HEATMAPS_RECORDING_CLICKMAP: 'heatmaps-recording-clickmap', // owner: #team-web-analytics
    IMPROVED_COOKIELESS_MODE: 'improved-cookieless-mode', // owner: #team-web-analytics
    LINEAGE_DEPENDENCY_VIEW: 'lineage-dependency-view', // owner: #team-data-modeling
    MEMBERS_CAN_USE_PERSONAL_API_KEYS: 'members-can-use-personal-api-keys', // owner: @yasen-posthog #team-platform-features
    METRIC_INSIGHT: 'metric-insight', // owner: @sampennington #team-product-analytics
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
    SLACK_APP_OAUTH: 'slack-app-oauth', // owner: @VojtechBartos #team-platform-features
    SLOPE_GRAPH_INSIGHT: 'slope-graph-insight', // owner: @pauldambra #team-product-analytics
    STARTUP_PROGRAM_INTENT: 'startup-program-intent', // owner: @pawel-cebula #team-billing
    SURVEYS_ACTIONS: 'surveys-actions', // owner: #team-surveys
    SURVEYS_ADAPTIVE_LIMITS: 'surveys-adaptive-limits', // owner: #team-surveys
    SURVEYS_AI_FIRST_EMPTY_STATE: 'surveys-ai-first-empty-state', // owner: #team-surveys, enables ai-first empty state
    SURVEYS_HOSTED_EDITOR: 'surveys-hosted-editor', // owner: #team-surveys, enables the dedicated hosted-survey editor UI
    SURVEYS_REDESIGNED_VIEW: 'surveys-redesigned-view', // owner: #team-surveys, enables the redesigned survey view with sidebar
    SURVEYS_TRANSLATIONS: 'surveys-translations', // owner: #team-surveys
    TRACK_DETACHED_ELEMENTS: 'track-detached-elements', // owner: @pauldambra #team-replay
    TRACK_MEMORY_USAGE: 'track-memory-usage', // owner: @pauldambra #team-replay
    TRACK_REACT_FRAMERATE: 'track-react-framerate', // owner: @pauldambra #team-replay
    WEB_ANALYTICS_API: 'web-analytics-api', // owner: #team-web-analytics
    WEB_ANALYTICS_FOR_MOBILE: 'web-analytics-for-mobile', // owner: #team-web-analytics
    WEB_ANALYTICS_REFERRER_URL_DRILLDOWN: 'web-analytics-referrer-url-drilldown', // owner: @jabahamondes #team-web-analytics

    // Temporary feature flags, still WIP, should be removed eventually
    AA_TEST_BAYESIAN_LEGACY: 'aa-test-bayesian-legacy', // owner: #team-experiments
    AA_TEST_BAYESIAN_NEW: 'aa-test-bayesian-new', // owner: #team-experiments
    ACTION_REFERENCE_COUNT: 'action-reference-count', // owner: @andyzzhao #team-product-analytics, gates bulk action reference counting on actions list
    ADVANCE_MARKETING_ANALYTICS_SETTINGS: 'advance-marketing-analytics-settings', // owner: @jabahamondes  #team-web-analytics
    AI_GATEWAY: 'ai-gateway', // owner: #team-ai-gateway, gates the AI gateway UI and llm_gateway:read on project secret API keys
    AI_OBSERVABILITY_EVALUATIONS_TRACE_TARGET: 'ai-observability-evaluations-trace-target', // owner: #team-ai-observability
    /** Alert edit modal: check history chart + chart/table toggle (table remains when off). */
    ALERTS_15_MINUTE_INTERVAL: 'alerts-15-minute-interval', // owner: #team-analytics-platform, gates 15-minute insight alert interval
    ALERTS_ANOMALY_DETECTION: 'alerts-anomaly-detection', // owner: @andrewm4894
    ALERTS_INLINE_NOTIFICATIONS: 'alerts-inline-notifications', // owner: @vdekrijger
    ALERTS_INVESTIGATION_AGENT: 'alerts-investigation-agent', // owner: @andrewm4894, anomaly alerts — investigation agent on firing
    ALERTS_REAL_TIME_INTERVAL: 'alerts-real-time-interval', // owner: #team-analytics-platform, gates real-time (2-minute) insight alert interval
    AMPLITUDE_BATCH_IMPORT_OPTIONS: 'amplitude-batch-import-options', // owner: #team-ingestion
    APPROVALS: 'approvals', // owner: @yasen-posthog #team-platform-features
    AVERAGE_PAGE_VIEW_COLUMN: 'average-page-view-column', // owner: @jordanm-posthog #team-web-analytics
    BACKFILL_WORKFLOWS_DESTINATION: 'backfill-workflows-destination', // owner: #team-batch-exports
    CDP_ACTIVITY_LOG_NOTIFICATIONS: 'cdp-activity-log-notifications', // owner: #team-workflows-cdp
    CDP_DWH_TABLE_SOURCE: 'cdp-dwh-table-source', // owner: #team-workflows-cdp
    CDP_HOG_SOURCES: 'cdp-hog-sources', // owner #team-workflows-cdp
    CDP_MICROSOFT_ADS: 'cdp-microsoft-ads', // owner: #team-workflows-cdp
    CDP_NEW_PRICING: 'cdp-new-pricing', // owner: #team-workflows
    CDP_PERSON_UPDATES: 'cdp-person-updates', // owner: #team-workflows-cdp
    CDP_VERCEL_LOG_DRAIN: 'cdp-vercel-log-drain', // owner: #team-workflows-cdp
    COHORT_INLINE_CALCULATION: 'inline-cohort-calculation', // owner: #team-analytics-platform, inlines fast dynamic cohort queries instead of using precomputed cohortpeople table
    COHORTS_TAXONOMIC_BASIC_LIST: 'cohorts-taxonomic-basic-list', // owner: @adamleith, picker sends ?basic=true to the cohorts list endpoint (trimmed payload: no filters/query/groups)
    CONDENSED_FILTER_BAR: 'condensed_filter_bar', // owner: @jordanm-posthog #team-web-analytics
    CREATE_FORM_TOOL: 'phai-create-form-tool', // owner: @kappa90 #team-posthog-ai
    CRM_ITERATION_ONE: 'crm-iteration-one', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_ANALYTICS: 'customer-analytics-roadmap', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_ANALYTICS_CSP: 'customer-analytics-csp', // owner: @arthurdedeus #team-customer-analytics, gates the Customer analytics > Accounts settings tab (account_group_type_index dropdown)
    CUSTOMER_ANALYTICS_JOURNEYS: 'customer-analytics-journeys', // owner: @arthurdedeus #team-customer-analytics
    CUSTOMER_PROFILE_CONFIG_BUTTON: 'customer-profile-config-button', // owner: @arthurdedeus #team-customer-analytics
    DASHBOARD_AUTO_PREVIEW_LIMIT: 'dashboard-auto-preview-limit', // owner: @pauldambra #team-product-analytics
    DASHBOARD_INLINE_TILE_INSERTION: 'dashboard-inline-tile-insertion', // owner: @MattPua #team-analytics-platform
    DASHBOARD_LAYOUT_DISCARD_PROMPT: 'dashboard-layout-discard-prompt', // owner: @cory.s #team-analytics-platform
    DASHBOARD_QUICK_FILTERS_EXPERIMENT: 'dashboard-quick-filters-experiment', // owner: @vdekrijger #team-product-analytics multivariate=control,test
    DASHBOARD_SUBSCRIBE_PLACEMENT: 'dashboard-subscribe-placement', // owner: @MattPua #team-analytics-platform multivariate=control,button,menu
    DASHBOARD_TEMPLATE_CHOOSER_EXPERIMENT: 'dashboard-template-chooser-experiment', // owner: @mattp #team-analytics-platform multivariate=control,simple,new
    DASHBOARD_WIDGETS: 'dashboard-widgets', // owner: @mattp #team-analytics-platform
    DASHBOARDS_LIST_VIEW: 'dashboards-list-view', // owner: @vdekrijger #team-product-analytics multivariate=control,tree
    DATA_MODELING_BACKEND_V2: 'data-modeling-backend-v2', // owner: #team-data-modeling
    DATA_MODELING_MULTI_DAG: 'data-modeling-multi-dag', // owner: #team-data-modeling
    DATA_MODELING_SEMANTIC_ENRICHMENT: 'data-modeling-semantic-enrichment', // owner: #team-data-modeling
    DATA_MODELING_TAB: 'data-modeling-tab', // owner: #team-data-modeling
    DATA_WAREHOUSE_COLUMN_STATISTICS: 'data-warehouse-column-statistics', // owner: #team-warehouse-sources
    DATA_WAREHOUSE_CUSTOM_SOURCE_AI_BUILDER: 'dwh-custom-source-ai-builder', // owner: #team-warehouse-sources
    DATA_WAREHOUSE_CUSTOM_SOURCE_OAUTH2: 'dwh-custom-source-oauth2', // owner: #team-warehouse-sources
    DATA_WAREHOUSE_SCENE: 'data-warehouse-scene', // owner: #team-data-modeling
    DATA_WAREHOUSE_SEMANTIC_ENRICHMENT: 'data-warehouse-semantic-enrichment', // owner: #team-warehouse-sources
    DEFAULT_EVALUATION_ENVIRONMENTS: 'default-evaluation-environments', // owner: @dmarticus #team-feature-flags
    DROP_PERSON_LIST_ORDER_BY: 'drop-person-list-order-by', // owner: @arthurdedeus #team-customer-analytics
    DWH_JOIN_TABLE_PREVIEW: 'dwh-join-table-preview', // owner: @arthurdedeus #team-customer-analytics
    DWH_POSTGRES_CDC: 'dwh-postgres-cdc', // owner: #team-warehouse-sources
    DWH_POSTGRES_XMIN: 'dwh-postgres-xmin', // owner: #team-warehouse-sources
    DWH_SOURCE_METRICS: 'dwh-source-metrics', // owner: #team-warehouse-sources
    EDITOR_DRAFTS: 'editor-drafts', // owner: @EDsCODE #team-data-tools
    ENDPOINTS: 'embedded-analytics', // owner: @sakce #team-clickhouse
    ENGINEERING_ANALYTICS: 'engineering-analytics', // owner: #team-devex
    ERROR_TRACKING_ISSUE_CORRELATION: 'error-tracking-issue-correlation', // owner: @david #team-error-tracking
    ERROR_TRACKING_ISSUE_SPLITTING: 'error-tracking-issue-splitting', // owner: @david #team-error-tracking
    ERROR_TRACKING_RATE_LIMITING: 'error-tracking-rate-limiting', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_RATE_LIMITING_BYPASS: 'error-tracking-rate-limiting-bypass', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_RATE_LIMITING_PER_ISSUE: 'error-tracking-rate-limiting-per-issue', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_RECOMMENDATIONS: 'error-tracking-recommendations', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_RELATED_ISSUES: 'error-tracking-related-issues', // owner: #team-error-tracking
    ERROR_TRACKING_SOURCE_MAPS_BANNER: 'error-tracking-source-maps-banner', // owner: @ablaszkiewicz #team-error-tracking
    ERROR_TRACKING_WEEKLY_DIGEST: 'error-tracking-weekly-digest', // owner: #team-error-tracking
    EVENT_MEDIA_PREVIEWS: 'event-media-previews', // owner: @alexlider
    EXPERIMENT_SESSION_REPLAYS_SKILL: 'experiment-session-replays-skill', // owner: @rodrigoi #team-experiments
    EXPERIMENTS_DW_AA_TEST: 'experiments-dw-aa-test', // owner: @rodrigoi #team-experiments
    EXPERIMENTS_END_MODAL_CONCLUSION_FIRST: 'experiments-end-modal-conclusion-first', // owner: @ruby.c #team-experiments
    EXPERIMENTS_EXCLUDED_VARIANTS: 'experiments-excluded-variants', // owner: @rodrigoi #team-experiments
    EXPERIMENTS_METRICS_RECALCULATION: 'experiments-metrics-recalculation', // owner: @rodrigoi #team-experiments
    EXPERIMENTS_SHOW_SQL: 'experiments-show-sql', // owner: @jurajmajerik #team-experiments
    EXPERIMENTS_SYNC_QUERIES: 'experiments-sync-queries', // owner: @andehen #team-experiments
    EXPERIMENTS_TEMPLATES: 'experiments-templates', // owner: @rodrigoi #team-experiments
    FEATURE_FLAG_COHORT_CREATION: 'feature-flag-cohort-creation', // owner: #team-feature-flags
    FEATURE_FLAG_CREATION_INTENTS: 'feature-flag-creation-intents', // owner: #team-feature-flags
    FEATURE_FLAG_DRAG_DROP_CONDITIONS: 'feature-flag-drag-drop-conditions', // owner: @gustavo #team-feature-flags
    FEATURE_FLAG_EARLY_EXIT: 'feature-flag-early-exit', // owner: @gustavo #team-feature-flags
    FEATURE_FLAG_NOTIFICATIONS: 'feature-flag-notifications', // owner: @reecejones #team-platform-features
    FEATURE_FLAG_USAGE_DASHBOARD_CHECKBOX: 'feature-flag-usage-dashboard-checkbox', // owner: #team-feature-flags, globally disabled, enables opt-out of auto dashboard creation
    FIELD_NOTES: 'field-notes', // owner: @adamleith
    FLAG_EVALUATION_TAGS: 'flag-evaluation-tags', // owner: @dmarticus #team-feature-flags
    FLAGGED_FEATURE_INDICATOR: 'flagged-feature-indicator', // owner: @benjackwhite
    FUNNEL_INSIGHT_ALERTS: 'funnel-insight-alerts', // owner: @vdekrijger, gates alerts on funnel insights (conversion rate)
    GROUP_PROFILE_EXPERIMENT: 'group-profile-experiment', // owner: @arthurdedeus #team-customer-analytics
    HEALTH_ASK_AI: 'health-ask-ai', // owner: @jordanm-posthog #team-web-analytics, gates the "Ask PostHog AI" buttons on the Health overview
    HOG_INVOCATION_RESULTS_RUNS_TAB: 'hog-invocation-results-runs-tab', // owner: #team-workflows
    HOGQL_INSIGHT_ALERTS: 'hogql-insight-alerts', // owner: @vdekrijger, gates alerts on SQL-backed (HogQL) insights
    HOGQL_WAREHOUSE_ACCESS_CONTROL: 'hogql-warehouse-access-control', // owner: @a-lider #team-platform-features, gates per-object access control for warehouse tables and views
    IDENTITY_MATCHING: 'identity-matching', // owner: @fercgomes #team-growth, gates new identity matching scene on marketing analytics
    INBOX_SLACK_NOTIFICATIONS: 'inbox-slack-notifications', // owner: #team-self-driving, gates the Slack notifications config card in the inbox
    INSIGHT_SUBSCRIBE_PROMINENT_BUTTON: 'insight-subscribe-prominent-button', // owner: @mattp #team-analytics-platform multivariate=control,test
    INTER_PROJECT_TRANSFERS: 'inter-project-transfers', // owner: @reecejones #team-platform-features
    JS_SNIPPET_VERSIONING: 'js-snippet-versioning', // owner: #team-client-libraries
    LINKS: 'links', // owner: @marconlp #team-link (team doesn't exist for now, maybe will come back in the future)
    LIVE_DEBUGGER: 'live-debugger', // owner: @marcecoll
    LIVE_EVENTS_RICH_FILTERS: 'live-events-rich-filters', // owner: @jordanm-posthog #team-web-analytics
    LLM_ANALYTICS_CLUSTERING_ADMIN: 'llm-analytics-clustering-admin', // owner: #team-ai-observability
    LLM_ANALYTICS_CUSTOM_PARSERS: 'ai-observability-custom-parsers', // owner: #team-ai-observability
    LLM_ANALYTICS_DATASETS: 'llm-analytics-datasets', // owner: #team-ai-observability #team-posthog-ai
    LLM_ANALYTICS_EARLY_ADOPTERS: 'llm-analytics-early-adopters', // owner: #team-ai-observability
    LLM_ANALYTICS_EVALUATIONS_REPORTS: 'llm-analytics-evaluations-reports', // owner: #team-ai-observability
    LLM_ANALYTICS_EVALUATIONS_SENTIMENT: 'llm-analytics-sentiment-evaluations', // owner: #team-ai-observability
    LLM_ANALYTICS_OFFLINE_EVALS: 'llm-analytics-offline-evals', // owner: #team-ai-observability
    LLM_ANALYTICS_TAGS: 'llm-analytics-tags', // owner: #team-ai-observability
    LLM_ANALYTICS_TRACE_NAVIGATION: 'llm-analytics-trace-navigation', // owner: #team-ai-observability
    LLM_ANALYTICS_USER_FEEDBACK: 'llm-analytics-user-feedback', // owner: @adboio #team-surveys
    LLM_OBSERVABILITY_SHOW_INPUT_OUTPUT: 'llm-observability-show-input-output', // owner: #team-ai-observability
    LOGS: 'logs', // owner: #team-logs
    LOGS_ALERTING: 'logs-alerting', // owner: #team-logs
    LOGS_GROUP_BY: 'logs-group-by', // owner: #team-logs
    LOGS_PATTERNS_VIEW: 'logs-patterns-view', // owner: #team-logs
    LOGS_SAVED_VIEWS: 'logs-saved-views', // owner: #team-logs
    LOGS_SERVICES_VIEW: 'logs-services-view', // owner: #team-logs
    LOGS_SETTINGS: 'logs-settings', // owner: #team-logs
    LOGS_SETTINGS_DROP_RULES: 'logs-settings-drop-rules', // owner: #team-logs
    LOGS_SETTINGS_JSON: 'logs-settings-json', // owner: #team-logs
    LOGS_SETTINGS_PII_SCRUB: 'logs-settings-pii-scrub', // owner: #team-logs
    LOGS_SETTINGS_RETENTION: 'logs-settings-retention', // owner: #team-logs
    LOGS_SPARKLINE_SERVICE_BREAKDOWN: 'logs-sparkline-service-breakdown', // owner: #team-logs
    LOGS_SQL_VIEW: 'logs-sql-view', // owner: #team-logs
    LOGS_TABBED_VIEW: 'logs-tabbed-view', // owner: #team-logs
    MANAGED_VIEWSETS: 'managed-viewsets', // owner: @rafaeelaudibert #team-revenue-analytics
    MARKDOWN_NOTEBOOKS: 'markdown-notebooks', // owner: #team-platform-features, enables Markdown notebooks upgrade path
    MARKETING_ANALYTICS_AI: 'marketing-analytics-ai', // owner: @jabahamondes #team-web-analytics
    MARKETING_ANALYTICS_COSTS_PRECOMPUTATION: 'marketing-analytics-costs-precomputation', // owner: @jabahamondes #team-web-analytics — gates reading the native cost precompute table
    MARKETING_ANALYTICS_DRILL_DOWN: 'marketing-analytics-drill-down', // owner: @jabahamondes  #team-web-analytics
    MARKETING_ANALYTICS_EXTENDED_DRILL_DOWN: 'marketing-analytics-extended-drill-down', // owner: @jabahamondes  #team-web-analytics
    MARKETING_ANALYTICS_MCP: 'marketing-analytics-mcp', // owner: @jabahamondes #team-web-analytics — gates MCP tool exposure (read-only marketing-analytics tools)
    MARKETING_ANALYTICS_MULTI_TOUCH_ATTRIBUTION: 'marketing-analytics-multi-touch-attribution', // owner: @jabahamondes #team-web-analytics
    MARKETING_ANALYTICS_NEW_DASHBOARD: 'new-marketing-analytics-dashboard', // owner: @jabahamondes #team-web-analytics — gates the WIP redesigned dashboard tab
    MARKETING_ANALYTICS_UTM_AUDIT: 'marketing-analytics-utm-audit', // owner: @jabahamondes  #team-web-analytics
    MAX_AI_INSIGHT_SEARCH: 'max-ai-insight-search', // owner: #team-posthog-ai
    MAX_BILLING_CONTEXT: 'max-billing-context', // owner: @pawel-cebula #team-billing
    MAX_DEEP_RESEARCH: 'max-deep-research', // owner: @kappa90 #team-posthog-ai
    MAX_HANDS_FREE: 'max-hands-free', // owner: #team-posthog-ai
    MAX_HOMEPAGE_CAPABILITIES: 'max-homepage-capabilities', // owner: @rafaeelaudibert #team-posthog-ai multivariate=control,behaviors,products — /home capability badges grouped by behavior vs product
    MAX_WEB_ANALYTICS_NUDGE: 'posthog-ai-web-analytics-nudge', // owner: @jordanm-posthog #team-web-analytics
    MCP_ANALYTICS: 'mcp-analytics', // owner: #project-mcp-analytics
    MCP_ANALYTICS_INTENT_ROUTING: 'mcp-analytics-intent-routing', // owner: #project-mcp-analytics
    MCP_SERVERS: 'mcp-servers', // owner: #team-posthog-ai
    MESSAGING_SES: 'messaging-ses', // owner #team-workflows
    METRICS: 'metrics', // owner: #team-apm (@jonmcwest, @frankh)
    NEW_TAB_PROJECT_EXPLORER: 'new-tab-project-explorer', // owner: #team-platform-ux
    NEW_TEAM_CORE_EVENTS: 'new-team-core-events', // owner: @jabahamondes #team-web-analytics
    NOTEBOOK_PYTHON: 'notebook-python', // owner: #team-data-tools
    NOTEBOOK_SHARING: 'notebook-sharing', // owner: @reecejones #team-platform-features
    NOTEBOOKS_COLLABORATION: 'notebooks-collaboration', // owner: #team-platform-features
    NOTEBOOKS_COLLAPSIBLE_SECTIONS: 'notebooks-collapsible-sections', // owner: @benjackwhite
    ONBOARDING_DATA_WAREHOUSE_VALUE_PROP: 'onboarding-data-warehouse-value-prop', // owner: @fercgomes #team-growth multivariate=control,table,query
    ONBOARDING_FLOW_VARIANT: 'onboarding-flow-variant', // owner: @fercgomes #team-growth multivariate=control,self-driving — selects the whole onboarding experience; control is the existing flow (the historical `legacy` value is an alias of control)
    ONBOARDING_HIDE_BREADCRUMBS: 'onboarding-hide-breadcrumbs', // owner: @fercgomes #team-growth, multivariate=true, hides breadcrumbs during onboarding to reduce distractions
    ONBOARDING_MOBILE_INSTALL_HELPER: 'onboarding-mobile-install-helper', // owner: @fercgomes #team-growth multivariate=control,test — target $device_type=Mobile at the flag level
    ONBOARDING_NAVBAR: 'onboarding-navbar', // owner: @fercgomes #team-growth, hides the navbar during onboarding to reduce distractions multivariate=true
    ONBOARDING_PLATFORM_PACKAGES: 'onboarding-platform-packages', // owner: @mjwarren3 #team-growth multivariate=control,test — surfaces platform packages with a free trial on the plans step after subscribing
    ONBOARDING_PRODUCT_SELECTION_HEADING: 'onboarding-product-selection-heading', // owner: @fercgomes #team-growth, payload overrides the heading copy on the first onboarding page
    ONBOARDING_SESSION_REPLAY_MEDIA: 'onboarding-session-replay-media', // owner: @fercgomes #team-growth multivariate=control,screenshot,demo
    ONBOARDING_SOCIAL_PROOF_INFO: 'onboarding-social-proof-info', // owner: @fercgomes #team-growth, payload overrides social proof strings per product
    ONBOARDING_WIZARD_CLOUD_RUN: 'onboarding-wizard-cloud-run', // owner: @fercgomes #team-growth multivariate=control,test — gates the "open a PR for me" cloud wizard option on the install step
    ONBOARDING_WIZARD_SIDEBAR: 'onboarding-wizard-sidebar', // owner: @fercgomes #team-growth multivariate=control,test — gates the installation status item in the sidebar footer
    ONBOARDING_WIZARD_SYNC: 'onboarding-wizard-sync', // owner: @fercgomes #team-growth multivariate=control,test — gates the live wizard sync progress panel
    ONBOARDING_WIZARD_SYNC_MODE: 'onboarding-wizard-sync-mode', // owner: @fercgomes #team-growth multivariate=sse,polling — how the wizard sync panel pulls run updates (SSE stream vs REST polling); payload carries polling_interval_secs
    OWNER_ONLY_BILLING: 'owner-only-billing', // owner: @pawelcebula #team-billing
    PAGE_REPORTS_AVERAGE_PAGE_VIEW: 'page-reports-average-page-view', // owner: @jordanm-posthog #team-web-analytics
    PAGE_REPORTS_RANKED_URL_SEARCH: 'page-reports-ranked-url-search', // owner: @jordanm-posthog #team-web-analytics
    PASSKEY_SIGNUP_ENABLED: 'passkey-signup-enabled', // owner: @reecejones #team-platform-features
    PASSWORD_PROTECTED_SHARES: 'password-protected-shares', // owner: @aspicer
    PHAI_PLAN_MODE: 'phai-plan-mode', // owner: #team-posthog-ai
    PHAI_SANDBOX_MODE: 'phai-sandbox-mode', // owner: #team-posthog-ai
    PHAI_TASKS: 'phai-tasks', // owner: #team-array
    PIPELINE_STATUS_PAGE: 'pipeline-status-page', // owner: @clr182 #team-support
    POSTHOG_AI_BILLING_DISPLAY: 'posthog-ai-billing-display', // owner: #team-posthog-ai
    POSTHOG_AI_CHANGELOG: 'posthog-ai-changelog', // owner: #team-posthog-ai
    POSTHOG_AI_CONVERSATION_FEEDBACK_CONFIG: 'posthog-ai-conversation-feedback-config', // owner: #team-posthog-ai
    POSTHOG_AI_CONVERSATION_FEEDBACK_LLMA_SESSIONS: 'posthog-ai-conversation-feedback-llma-sessions', // owner: #team-posthog-ai
    POSTHOG_AI_QUEUE_MESSAGES_SYSTEM: 'posthog-ai-queue-messages-system', // owner: #team-posthog-ai
    POSTHOG_CODE_BILLING: 'posthog-code-billing', // owner: #team-posthog-code
    PRODUCT_ANALYTICS_DASHBOARD_COLORS: 'dashboard-colors', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS: 'product-analytics-dashboard-modal-smart-defaults', // owner: @sam #team-product-analytics
    PRODUCT_ANALYTICS_FUNNELS_COMPARE: 'product-analytics-funnels-compare', // owner: @thmsobrmlr #team-product-analytics, gates "Compare to previous" toggle on funnel insights
    PRODUCT_ANALYTICS_HIDE_WEEKENDS: 'product-analytics-hide-weekends', // owner: @kliment-slice #team-irl-events
    PRODUCT_ANALYTICS_INSIGHT_HORIZONTAL_CONTROLS: 'insight-horizontal-controls', // owner: #team-product-analytics
    PRODUCT_ANALYTICS_INSIGHTS_TOOLTIPS: 'product-analytics-insights-tooltips', // owner: #team-product-analytics, gates the unified quill DefaultTooltip for trends/retention/stickiness insight charts
    PRODUCT_ANALYTICS_PATHS_V2: 'paths-v2', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_ANALYTICS_QUILL_LEGEND: 'product-analytics-quill-legend', // owner: #team-product-analytics, gates the in-chart quill legend replacing the legacy side InsightLegend
    PRODUCT_ANALYTICS_QUILL_SQL_CHARTS: 'product-analytics-quill-sql-charts', // owner: #team-data-tools, gates rendering DataVisualization line/area charts via @posthog/quill-charts
    PRODUCT_ANALYTICS_RETENTION_AGGREGATION: 'retention-aggregation', // owner: @anirudhpillai #team-product-analytics
    PRODUCT_ANALYTICS_RETENTION_DWH: 'retention-dwh', // owner: @thmsobrmlr #team-product-analytics
    PRODUCT_AUTONOMY: 'product-autonomy', // owner: #team-self-driving
    PRODUCT_BUSINESS_KNOWLEDGE: 'product-business-knowledge', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_AI_SUGGESTION: 'product-support-ai-suggestion', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_CREATE_TICKET: 'product-support-create-ticket', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_GITHUB_CHANNEL: 'product-support-github-channel', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_IMPORT_TICKETS: 'product-support-import-tickets', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_SIDE_PANEL: 'product-support-side-panel', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_SLACK_NOTIFY_ON_MEMBERS: 'product-support-slack-notify-on-members', // owner: @veryayskiy #team-conversations
    PRODUCT_SUPPORT_TEAMS_ENABLED: 'product-support-teams-enabled', // owner: @veryayskiy #team-conversations
    PRODUCT_TOURS: 'product-tours-2025', // owner: @adboio #team-surveys
    PRODUCT_TOURS_LOCALIZATION: 'product-tours-localization', // owner: @adboio #team-surveys
    PROJECT_SECRET_API_KEYS: 'project-secret-api-keys', // owner: #team-platform-features
    PROMOTED_EVENT_PROPERTIES_EDIT: 'promoted-event-properties-edit', // owner: @pauldambra #team-product-analytics, gates the primary-property picker on the event definition edit page (flag slug kept as `promoted-event-properties-edit` to avoid migrating teams that already toggled it on)
    PROPERTY_ACCESS_CONTROL: 'property-access-control', // owner: @reecejones #team-platform-features
    QUICK_START_PULSE_INDICATOR: 'quick-start-pulse-indicator', // owner: @fercgomes #team-growth multivariate=control,test
    QUILL_CHART_STYLE_REFRESH: 'quill-chart-style-refresh', // owner: #team-product-analytics, gates refreshed quill chart styling (monotone curves, axis lines + tick marks, faint dashed grid, crosshair)
    QUILL_DATE_PICKER: 'quill-date-picker', // owner: @pauldambra, flips the lib/components/DatePicker seam from LemonUI to Quill
    RBAC_UI_REDESIGN: 'rbac-ui-redesign', // owner: @reece #team-platform-features
    READ_ONLY_MODE: 'read-only-mode', // owner: @pauldambra, experiment: force users into read-only and steer mutations through Max/MCP
    REAL_TIME_NOTIFICATIONS: 'real-time-notifications', // owner: #team-platform-features
    REALTIME_COHORT_FLAG_TARGETING: 'realtime-cohort-flag-targeting', // owner: @dmarticus #team-feature-flags
    RECORDINGS_PLAYER_EVENT_PROPERTY_EXPANSION: 'recordings-player-event-property-expansion', // owner: @pauldambra #team-replay
    REMOTE_CONFIG: 'remote-config', // owner: #team-platform-features
    REPLAY_COLLAPSE_INSPECTOR_ITEMS: 'replay-collapse-inspector-items', // owner: @fasyy612 #team-replay
    REPLAY_FILTERS_REDESIGN: 'replay-filters-redesign', // owner: @ksvat #team-replay
    REPLAY_PLAYLIST_RELEVANCE_SORT_EXPERIMENT: 'replay-playlist-relevance-sort-experiment', // owner: @arnohillen #team-replay multivariate=control,test
    REPLAY_PLAYLIST_SURFACING_SCORE: 'replay-playlist-surfacing-score', // owner: #team-replay
    REPLAY_TRIGGERS_V2: 'replay-triggers-v2', // owner: #team-replay
    REPLAY_UI_REDESIGN_2026: 'replay-ui-redesign-2026', // owner: #team-replay, New UI layout for replay
    REPLAY_VIDEO_BASED_SUMMARIZATION: 'replay-video-based-summarization', // owner: #team-replay
    REPLAY_VISION: 'replay-vision', // owner: #team-replay
    REPLAY_VISION_ACTIONS: 'replay-vision-actions', // owner: #team-replay
    REPLAY_VISION_QUALITY: 'replay-vision-quality', // owner: #team-replay
    REVAMPED_PY_NOTEBOOKS: 'revamped-py-notebooks', // owner: #team-data-tools
    REVENUE_ANALYTICS: 'revenue-analytics', // owner: @rafaeelaudibert #team-customer-analytics
    REVENUE_FIELDS_IN_POWER_USERS_TABLE: 'revenue-fields-in-power-users-table', // owner: @arthurdedeus #team-customer-analytics
    SCENE_MENU_BAR: 'scene-menu-bar', // owner: @adamleithp #team-platform-ux, gates the per-scene MenuBar above SceneTitleSection
    SCHEMA_ENFORCEMENT_REJECT: 'schema-enforcement-reject', // owner: @aspicer, gates the ability to set schema enforcement mode to "reject"
    SCHEMA_MANAGEMENT: 'schema-management', // owner: @aspicer
    SEARCH_DEBOUNCE_ALL: 'search-debounce-all', // owner: @adamleithp #team-platform-ux
    SEARCH_RE_RANK: 'search-re-rank', // owner: @adamleithp #team-platform-ux
    SEEKBAR_PREVIEW_SCRUBBING: 'seekbar-preview-scrubbing', // owner: @pauldambra #team-replay
    SHOPIFY_DWH: 'shopify-dwh', // owner: #team-warehouse-sources
    SHOW_DATA_PIPELINES_NAV_ITEM: 'show-data-pipelines-nav-item', // owner: @raquelmsmith
    SHOW_REFERRER_FAVICON: 'show-referrer-favicon', // owner: @jordanm-posthog #team-web-analytics
    SHOW_REPLAY_FILTERS_FEEDBACK_BUTTON: 'show-replay-filters-feedback-button', // owner: @ksvat #team-replay
    SIGNUP_AA_TEST_4_WAY: 'signup-aa-test-4-way', // owner: @andehen #team-experiments multivariate=control,test-1,test-2,test-3
    SLACK_DWH: 'slack-dwh', // owner: @MarconLP #team-warehouse-sources
    SQL_EDITOR_VIM_MODE: 'sql-editor-vim-mode', // owner: @arthurdedeus
    SSE_DASHBOARDS: 'sse-dashboards', // owner: @aspicer #team-analytics-platform
    SUBSCRIPTION_AI_PROMPT: 'ai-subscriptions', // owner: #team-analytics-platform, gates AI prompt-based subscriptions
    SUBSCRIPTION_AI_SUMMARY_PROMPT_GUIDE: 'subscription-ai-summary-prompt-guide', // owner: #team-analytics-platform, gates the per-subscription prompt guide textarea
    SURVEY_HEADLINE_SUMMARY: 'survey-headline-summary', // owner: @adboio #team-surveys
    SURVEYS_ERROR_TRACKING_CROSS_SELL: 'surveys-in-error-tracking', // owner: @adboio #team-surveys
    SURVEYS_FORM_BUILDER: 'surveys-form-builder', // owner: @adboio #team-surveys
    SURVEYS_INSIGHT_BUTTON_EXPERIMENT: 'ask-users-why-ai-vs-quickcreate', // owner: @adboio #team-surveys multivariate=true
    SURVEYS_TOOLBAR: 'surveys-toolbar', // owner: @fcgomes
    SURVEYS_WEB_ANALYTICS_CROSS_SELL: 'surveys-in-web-analytics', // owner: @adboio #team-surveys
    TASK_SUMMARIES: 'task-summaries', // owner: #team-ai-observability
    TASK_TOOL: 'phai-task-tool', // owner: @kappa90 #team-posthog-ai
    TASKS: 'tasks', // owner: #team-ai-observability
    TASKS_STREAM_VIA_PROXY: 'tasks-stream-via-proxy', // owner: #team-ai-observability
    TAXONOMIC_FILTER_CATEGORY_DROPDOWN: 'taxonomic-filter-category-dropdown', // owner: @pauldambra #team-product-analytics multivariate=control,pill
    TAXONOMIC_FILTER_DEFAULT_PINS: 'taxonomic-filter-default-pins', // owner: @pauldambra #team-product-analytics, seeds $current_url/email default pinned filters
    TAXONOMIC_FILTER_MENU_REBUILD: 'taxonomic-filter-menu-rebuild', // owner: @adamleith, opt-in to the rebuilt TaxonomicFilter — headless filter panel + new popover menu (column / preview-pane)
    TOOLBAR_HEATMAP_AREA_FILTER: 'toolbar-heatmap-area-filter', // owner: @pauldambra #team-replay, gates the target button that filters the toolbar heatmap/clickmap to a chosen page area
    TRACING: 'tracing', // owner: #team-apm (@jonmcwest, @frankh)
    TRACING_FACET_RAIL: 'tracing-facet-rail', // owner: #team-apm — gates the facet rail (faceted filter sidebar) in tracing
    TRACING_OPERATIONS_VIEW: 'tracing-operations-view', // owner: #team-apm — gates the Operations (per-operation aggregate) tab in tracing
    TRACING_SAVED_VIEWS: 'tracing-saved-views', // owner: #team-apm — gates saved views (saved filter sets) in tracing
    TRAFFIC_TYPE_VIRTUAL_PROPERTIES: 'traffic-type-virtual-properties', // owner: #team-web-analytics
    USER_INTERVIEWS: 'user-interviews', // owner: @Twixes @jurajmajerik
    UX_REMOVE_SIDEPANEL: 'ux-remove-sidepanel', // owner: #team-surveys
    VISUAL_REVIEW: 'visual-review', // owner: #team-devex
    WEB_ANALYTICS_ACHIEVEMENTS: 'web-analytics-achievements', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_BOT_ANALYSIS: 'web-analytics-bot-analysis', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_CONVERSION_GOAL_PREAGG: 'web-analytics-conversion-goal-preagg', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_DRAG_TO_ZOOM: 'web-analytics-drag-to-zoom', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_EMPTY_ONBOARDING: 'web-analytics-empty-onboarding', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_FILTERS_V2: 'web-analytics-filters-v2', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_FOCUS_MODE: 'web-analytics-focus-mode', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_INCLUDE_HOST: 'web-analytics-include-host', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_LIVE_CITY_BREAKDOWN: 'web-analytics-live-city-breakdown', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_LIVE_MAP: 'web-analytics-live-map', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_LIVE_PERSON_DRILLDOWN: 'web-analytics-live-person-drilldown', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_MARKETING: 'marketing-analytics', // owner: @jabahamondes #team-web-analytics
    WEB_ANALYTICS_METRIC_CARDS: 'web-analytics-metric-cards', // owner: #team-web-analytics
    WEB_ANALYTICS_OPEN_URL: 'web-analytics-open-url', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_PRECOMPUTE_TOGGLE: 'web-analytics-precompute-toggle', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_RECAP: 'web-analytics-recap', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_REGIONS_MAP: 'web-analytics-regions-map', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_SESSION_PROPERTY_CHARTS: 'web-analytics-session-property-charts', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_SHARE_NUDGE_V2: 'web-analytics-share-nudge-v2', // owner: @jordanm-posthog #team-web-analytics multivariate=control,control_b,banner,export
    WEB_ANALYTICS_STREAK_CADENCE: 'web-analytics-streak-cadence', // owner: @jordanm-posthog #team-web-analytics multivariate=control,hybrid,daily-only,weekly-only
    WEB_ANALYTICS_TILE_HEADER_V2: 'web-analytics-tile-header-v2', // owner: @jordanm-posthog #team-web-analytics multivariate=control,test
    WEB_ANALYTICS_TILE_SKELETONS: 'web-analytics-tile-skeletons', // owner: @jordanm-posthog #team-web-analytics
    WEB_ANALYTICS_TILE_TOGGLES: 'web-analytics-tile-toggles', // owner: @lricoy #team-web-analytics
    WEB_ANALYTICS_TOOLTIP_COMPARISON_LABELS: 'web-analytics-tooltip-comparison-labels', // owner: @lricoy #team-web-analytics
    WORKFLOWS_BATCH_TRIGGERS: 'workflows-batch-triggers', // owner: #team-workflows
    WORKFLOWS_ENGAGEMENT_EVENTS: 'workflows-engagement-events', // owner: #team-workflows
    WORKFLOWS_INTERNAL_EVENT_FILTERS: 'workflows-internal-event-filters', // owner: @haven #team-workflows
    WORKFLOWS_PERSON_TIMEZONE: 'workflows-person-timezone', // owner: #team-workflows
    WORKFLOWS_PUSH_NOTIFICATIONS: 'workflows-push-notifications', // owner: @Odin #team-workflows
    WORKFLOWS_RECURRING_SCHEDULES: 'workflows-recurring-schedules', // owner: #team-workflows
    WORKFLOWS_WAIT_UNTIL_EVENT: 'workflows-wait-until-event', // owner: #team-workflows
    XAA_AUTHENTICATION: 'xaa-authentication', // owner: @reecejones #team-platform-features
} as const
export type FeatureFlagLookupKey = keyof typeof FEATURE_FLAGS
export type FeatureFlagKey = (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]

// Flags that affect globally-mounted UI (e.g. floating widgets in
// AuthenticatedShell). Scene stories that opt into STORYBOOK_FEATURE_FLAGS
// shouldn't accidentally enable these, because the resulting widgets render
// in every snapshot and pollute visual regression.
const STORYBOOK_OPT_OUT_FLAGS: FeatureFlagKey[] = [FEATURE_FLAGS.READ_ONLY_MODE]

export const STORYBOOK_FEATURE_FLAGS = Object.values(FEATURE_FLAGS).filter(
    (flag) => !STORYBOOK_OPT_OUT_FLAGS.includes(flag)
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
export const MOCK_NODE_PROCESS = {
    cwd: () => '',
    env: {},
} as unknown as NodeJS.Process

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
    [Region.DEV]: 'app.dev.posthog.dev',
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
export const LOGS_ALERT_ERRORED_EVENT_ID = '$logs_alert_errored'

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
