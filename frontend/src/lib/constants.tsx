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
export const MAX_EXPERIMENT_VARIANTS = 10
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
    KAFKA_INSPECTOR: 'kafka-inspector', // owner: @yakkomajuri
    HISTORICAL_EXPORTS_V2: 'historical-exports-v2', // owner @macobo
    INGESTION_WARNINGS_ENABLED: 'ingestion-warnings-enabled', // owner: @tiina303
    SESSION_RESET_ON_LOAD: 'session-reset-on-load', // owner: @benjackwhite
    DEBUG_REACT_RENDERS: 'debug-react-renders', // owner: @benjackwhite
    AUTO_ROLLBACK_FEATURE_FLAGS: 'auto-rollback-feature-flags', // owner: @EDsCODE
    ONBOARDING_V2_DEMO: 'onboarding-v2-demo', // owner: #team-growth
    QUERY_RUNNING_TIME: 'query_running_time', // owner: @mariusandra
    QUERY_TIMINGS: 'query-timings', // owner: @mariusandra
    QUERY_ASYNC: 'query-async', // owner: @webjunkie
    POSTHOG_3000_NAV: 'posthog-3000-nav', // owner: @Twixes
    HEDGEHOG_MODE: 'hedgehog-mode', // owner: @benjackwhite
    HEDGEHOG_MODE_DEBUG: 'hedgehog-mode-debug', // owner: @benjackwhite
    HIGH_FREQUENCY_BATCH_EXPORTS: 'high-frequency-batch-exports', // owner: @tomasfarias
    PERSON_BATCH_EXPORTS: 'person-batch-exports', // owner: @tomasfarias
    // owner: #team-replay, only to be enabled for PostHog team testing
    EXCEPTION_AUTOCAPTURE: 'exception-autocapture',
    FF_DASHBOARD_TEMPLATES: 'ff-dashboard-templates', // owner: @EDsCODE
    ARTIFICIAL_HOG: 'artificial-hog', // owner: @Twixes
    CS_DASHBOARDS: 'cs-dashboards', // owner: @pauldambra
    PRODUCT_SPECIFIC_ONBOARDING: 'product-specific-onboarding', // owner: @raquelmsmith
    REDIRECT_SIGNUPS_TO_INSTANCE: 'redirect-signups-to-instance', // owner: @raquelmsmith
    APPS_AND_EXPORTS_UI: 'apps-and-exports-ui', // owner: @benjackwhite
    HOGQL_DASHBOARD_ASYNC: 'hogql-dashboard-async', // owner: @webjunkie
    WEBHOOKS_DENYLIST: 'webhooks-denylist', // owner: #team-pipeline
    PIPELINE_UI: 'pipeline-ui', // owner: #team-pipeline
    PERSON_FEED_CANVAS: 'person-feed-canvas', // owner: #project-canvas
    FEATURE_FLAG_COHORT_CREATION: 'feature-flag-cohort-creation', // owner: @neilkakkar #team-feature-success
    INSIGHT_HORIZONTAL_CONTROLS: 'insight-horizontal-controls', // owner: @benjackwhite
    SURVEYS_WIDGETS: 'surveys-widgets', // owner: #team-feature-success
    SURVEYS_EVENTS: 'surveys-events', // owner: #team-feature-success
    SURVEYS_ACTIONS: 'surveys-actions', // owner: #team-feature-success
    SURVEYS_RECURRING: 'surveys-recurring', // owner: #team-feature-success
    YEAR_IN_HOG: 'year-in-hog', // owner: #team-replay
    SESSION_REPLAY_EXPORT_MOBILE_DATA: 'session-replay-export-mobile-data', // owner: #team-replay
    DISCUSSIONS: 'discussions', // owner: #team-replay
    REDIRECT_INSIGHT_CREATION_PRODUCT_ANALYTICS_ONBOARDING: 'redirect-insight-creation-product-analytics-onboarding', // owner: @biancayang
    AI_SESSION_SUMMARY: 'ai-session-summary', // owner: #team-replay
    AI_SESSION_PERMISSIONS: 'ai-session-permissions', // owner: #team-replay
    PRODUCT_INTRO_PAGES: 'product-intro-pages', // owner: @raquelmsmith
    SESSION_REPLAY_DOCTOR: 'session-replay-doctor', // owner: #team-replay
    REPLAY_SIMILAR_RECORDINGS: 'session-replay-similar-recordings', // owner: #team-replay
    SAVED_NOT_PINNED: 'saved-not-pinned', // owner: #team-replay
    NEW_EXPERIMENTS_UI: 'new-experiments-ui', // owner: @jurajmajerik #team-feature-success
    REPLAY_ERROR_CLUSTERING: 'session-replay-error-clustering', // owner: #team-replay
    AUDIT_LOGS_ACCESS: 'audit-logs-access', // owner: #team-growth
    SUBSCRIBE_FROM_PAYGATE: 'subscribe-from-paygate', // owner: #team-growth
    SESSION_REPLAY_MOBILE_ONBOARDING: 'session-replay-mobile-onboarding', // owner: #team-replay
    HEATMAPS_UI: 'heatmaps-ui', // owner: @benjackwhite
    THEME: 'theme', // owner: @aprilfools
    INSIGHT_LOADING_BAR: 'insight-loading-bar', // owner: @aspicer
    PROXY_AS_A_SERVICE: 'proxy-as-a-service', // owner: #team-infrastructure
    LIVE_EVENTS: 'live-events', // owner: @zach or @jams
    SETTINGS_PERSONS_JOIN_MODE: 'settings-persons-join-mode', // owner: @robbie-c
    SETTINGS_PERSONS_ON_EVENTS_HIDDEN: 'settings-persons-on-events-hidden', // owner: @Twixes
    HOG: 'hog', // owner: @mariusandra
    HOG_FUNCTIONS: 'hog-functions', // owner: #team-cdp
    HOG_FUNCTIONS_LINKED: 'hog-functions-linked', // owner: #team-cdp
    PERSONLESS_EVENTS_NOT_SUPPORTED: 'personless-events-not-supported', // owner: @raquelmsmith
    ALERTS: 'alerts', // owner: github.com/nikitaevg
    ERROR_TRACKING: 'error-tracking', // owner: #team-replay
    SETTINGS_BOUNCE_RATE_PAGE_VIEW_MODE: 'settings-bounce-rate-page-view-mode', // owner: @robbie-c
    ONBOARDING_DASHBOARD_TEMPLATES: 'onboarding-dashboard-templates', // owner: @raquelmsmith
    MULTIPLE_BREAKDOWNS: 'multiple-breakdowns', // owner: @skoob13 #team-product-analytics
    WEB_ANALYTICS_LIVE_USER_COUNT: 'web-analytics-live-user-count', // owner: @robbie-c
    SETTINGS_SESSION_TABLE_VERSION: 'settings-session-table-version', // owner: @robbie-c
    INSIGHT_FUNNELS_USE_UDF: 'insight-funnels-use-udf', // owner: @aspicer #team-product-analytics
    FIRST_TIME_FOR_USER_MATH: 'first-time-for-user-math', // owner: @skoob13 #team-product-analytics
    MULTITAB_EDITOR: 'multitab-editor', // owner: @EDsCODE #team-data-warehouse
    WEB_ANALYTICS_REPLAY: 'web-analytics-replay', // owner: @robbie-c
    BATCH_EXPORTS_POSTHOG_HTTP: 'posthog-http-batch-exports',
    EXPERIMENT_MAKE_DECISION: 'experiment-make-decision', // owner: @jurajmajerik #team-feature-success
    WEB_ANALYTICS_CONVERSION_GOALS: 'web-analytics-conversion-goals', // owner: @robbie-c
    WEB_ANALYTICS_LAST_CLICK: 'web-analytics-last-click', // owner: @robbie-c
} as const
export type FeatureFlagKey = (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]

export const ENTITY_MATCH_TYPE = 'entities'
export const PROPERTY_MATCH_TYPE = 'properties'

export enum FunnelLayout {
    horizontal = 'horizontal',
    vertical = 'vertical',
}

export const BIN_COUNT_AUTO = 'auto' as const

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
]

export const UNSUBSCRIBE_SURVEY_ID = '018b6e13-590c-0000-decb-c727a2b3f462'
