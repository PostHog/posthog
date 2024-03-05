import { LemonSelectOptions } from '@posthog/lemon-ui'

import { ChartDisplayType, Region, SSOProvider } from '../types'

/** Display types which don't allow grouping by unit of time. Sync with backend NON_TIME_SERIES_DISPLAY_TYPES. */
export const NON_TIME_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.ActionsTable,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.WorldMap,
    ChartDisplayType.BoldNumber,
]
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
    // Cloud-only
    CLOUD_ANNOUNCEMENT: 'cloud-announcement',
    // Experiments / beta features
    FUNNELS_CUE_OPT_OUT: 'funnels-cue-opt-out-7301', // owner: @neilkakkar
    RETENTION_BREAKDOWN: 'retention-breakdown', // TODO: Dropped, remove
    SMOOTHING_INTERVAL: 'smoothing-interval', // owner: @timgl
    BILLING_LIMIT: 'billing-limit', // owner: @timgl
    KAFKA_INSPECTOR: 'kafka-inspector', // owner: @yakkomajuri
    HISTORICAL_EXPORTS_V2: 'historical-exports-v2', // owner @macobo
    PERSON_ON_EVENTS_ENABLED: 'person-on-events-enabled', //owner: @EDsCODE
    REGION_SELECT: 'region-select', // TODO: Rolled out, unflag
    INGESTION_WARNINGS_ENABLED: 'ingestion-warnings-enabled', // owner: @tiina303
    SESSION_RESET_ON_LOAD: 'session-reset-on-load', // owner: @benjackwhite
    DEBUG_REACT_RENDERS: 'debug-react-renders', // owner: @benjackwhite
    AUTO_ROLLBACK_FEATURE_FLAGS: 'auto-rollback-feature-flags', // owner: @EDsCODE
    ONBOARDING_V2_DEMO: 'onboarding-v2-demo', // owner: #team-growth
    ROLE_BASED_ACCESS: 'role-based-access', // owner: #team-experiments, @liyiy
    QUERY_RUNNING_TIME: 'query_running_time', // owner: @mariusandra
    QUERY_TIMINGS: 'query-timings', // owner: @mariusandra
    QUERY_ASYNC: 'query-async', // owner: @webjunkie
    POSTHOG_3000_NAV: 'posthog-3000-nav', // owner: @Twixes
    ENABLE_PROMPTS: 'enable-prompts', // owner: @lharries
    HEDGEHOG_MODE: 'hedgehog-mode', // owner: @benjackwhite
    HEDGEHOG_MODE_DEBUG: 'hedgehog-mode-debug', // owner: @benjackwhite
    GENERIC_SIGNUP_BENEFITS: 'generic-signup-benefits', // experiment, owner: @raquelmsmith
    WEB_ANALYTICS: 'web-analytics', // owner @robbie-c #team-web-analytics
    WEB_ANALYTICS_SAMPLING: 'web-analytics-sampling', // owner @robbie-c #team-web-analytics
    HIGH_FREQUENCY_BATCH_EXPORTS: 'high-frequency-batch-exports', // owner: @tomasfarias
    // owner: #team-replay, only to be enabled for PostHog team testing
    EXCEPTION_AUTOCAPTURE: 'exception-autocapture',
    DATA_WAREHOUSE: 'data-warehouse', // owner: @EDsCODE
    DATA_WAREHOUSE_POSTGRES_IMPORT: 'data-warehouse-postgres-import', // owner: @EDsCODE
    FF_DASHBOARD_TEMPLATES: 'ff-dashboard-templates', // owner: @EDsCODE
    SHOW_PRODUCT_INTRO_EXISTING_PRODUCTS: 'show-product-intro-existing-products', // owner: @raquelmsmith
    ARTIFICIAL_HOG: 'artificial-hog', // owner: @Twixes
    CS_DASHBOARDS: 'cs-dashboards', // owner: @pauldambra
    PRODUCT_SPECIFIC_ONBOARDING: 'product-specific-onboarding', // owner: @raquelmsmith
    REDIRECT_SIGNUPS_TO_INSTANCE: 'redirect-signups-to-instance', // owner: @raquelmsmith
    APPS_AND_EXPORTS_UI: 'apps-and-exports-ui', // owner: @benjackwhite
    HOGQL_INSIGHTS_LIFECYCLE: 'hogql-insights-lifecycle', // owner: @mariusandra
    HOGQL_INSIGHTS_PATHS: 'hogql-insights-paths', // owner: @webjunkie
    HOGQL_INSIGHTS_RETENTION: 'hogql-insights-retention', // owner: @webjunkie
    HOGQL_INSIGHTS_TRENDS: 'hogql-insights-trends', // owner: @Gilbert09
    HOGQL_INSIGHTS_STICKINESS: 'hogql-insights-stickiness', // owner: @Gilbert09
    HOGQL_INSIGHTS_FUNNELS: 'hogql-insights-funnels', // owner: @thmsobrmlr
    HOGQL_INSIGHT_LIVE_COMPARE: 'hogql-insight-live-compare', // owner: @mariusandra
    BI_VIZ: 'bi_viz', // owner: @Gilbert09
    HOGQL_AUTOCOMPLETE: 'hogql-autocomplete', // owner: @Gilbert09
    WEBHOOKS_DENYLIST: 'webhooks-denylist', // owner: #team-pipeline
    SURVEYS_RESULTS_VISUALIZATIONS: 'surveys-results-visualizations', // owner: @jurajmajerik
    SURVEYS_PAYGATES: 'surveys-paygates',
    PERSONS_HOGQL_QUERY: 'persons-hogql-query', // owner: @mariusandra
    PIPELINE_UI: 'pipeline-ui', // owner: #team-pipeline
    SESSION_RECORDING_SAMPLING: 'session-recording-sampling', // owner: #team-replay
    PERSON_FEED_CANVAS: 'person-feed-canvas', // owner: #project-canvas
    MULTI_PROJECT_FEATURE_FLAGS: 'multi-project-feature-flags', // owner: @jurajmajerik #team-feature-success
    FEATURE_FLAG_COHORT_CREATION: 'feature-flag-cohort-creation', // owner: @neilkakkar #team-feature-success
    INSIGHT_HORIZONTAL_CONTROLS: 'insight-horizontal-controls', // owner: @benjackwhite
    SURVEYS_WIDGETS: 'surveys-widgets', // owner: @liyiy
    SCHEDULED_CHANGES_FEATURE_FLAGS: 'scheduled-changes-feature-flags', // owner: @jurajmajerik #team-feature-success
    SESSION_REPLAY_MOBILE: 'session-replay-mobile', // owner: #team-replay
    INVITE_TEAM_MEMBER_ONBOARDING: 'invite-team-member-onboarding', // owner: @biancayang
    YEAR_IN_HOG: 'year-in-hog', // owner: #team-replay
    SESSION_REPLAY_EXPORT_MOBILE_DATA: 'session-replay-export-mobile-data', // owner: #team-replay
    DISCUSSIONS: 'discussions', // owner: #team-replay
    REDIRECT_INSIGHT_CREATION_PRODUCT_ANALYTICS_ONBOARDING: 'redirect-insight-creation-product-analytics-onboarding', // owner: @biancayang
    SIDEPANEL_STATUS: 'sidepanel-status', // owner: @benjackwhite
    NEW_FEATURE_FLAG_OPERATORS: 'new-feature-flag-operators', // owner: @neilkakkar
    AI_SESSION_SUMMARY: 'ai-session-summary', // owner: #team-replay
    AI_SESSION_PERMISSIONS: 'ai-session-permissions', // owner: #team-replay
    PRODUCT_INTRO_PAGES: 'product-intro-pages', // owner: @raquelmsmith
    DATANODE_CONCURRENCY_LIMIT: 'datanode-concurrency-limit', // owner: @robbie-c
    SESSION_REPLAY_DOCTOR: 'session-replay-doctor', // owner: #team-replay
    REPLAY_SIMILAR_RECORDINGS: 'session-replay-similar-recordings', // owner: #team-replay
    SAVED_NOT_PINNED: 'saved-not-pinned', // owner: #team-replay
    EXPORTS_SIDEPANEL: 'exports-sidepanel', // owner: #team-product-analytics
    BILLING_UPGRADE_LANGUAGE: 'billing-upgrade-language', // owner: @biancayang
    SESSION_REPLAY_V3_INGESTION_PLAYBACK: 'session-replay-v3-ingestion-playback', // owner: @benjackwhite
    SESSION_REPLAY_FILTER_ORDERING: 'session-replay-filter-ordering', // owner: #team-replay
    SESSION_REPLAY_LINKED_VARIANTS: 'session-replay-linked-variants', // owner: #team-replay
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

// If _any_ item on a dashboard is older than this, dashboard is automatically reloaded
export const AUTO_REFRESH_DASHBOARD_THRESHOLD_HOURS = 20

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
