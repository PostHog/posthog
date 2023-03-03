import { urls } from 'scenes/urls'
import { AvailableFeature, ChartDisplayType, LicensePlan, Region, SSOProviders } from '../types'

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
export enum OrganizationMembershipLevel {
    Member = 1,
    Admin = 8,
    Owner = 15,
}

export enum TeamMembershipLevel {
    Member = 1,
    Admin = 8,
}

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
]

// Event constants
export const ACTION_TYPE = 'action_type'
export const EVENT_TYPE = 'event_type'
export const STALE_EVENT_SECONDS = 30 * 24 * 60 * 60 // 30 days

// TODO: Deprecated; should be removed once backend is updated
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

export const FEATURE_FLAGS = {
    // Cloud-only
    CLOUD_ANNOUNCEMENT: 'cloud-announcement',
    // Experiments / beta features
    BREAKDOWN_BY_MULTIPLE_PROPERTIES: '938-breakdown-by-multiple-properties', // owner: @pauldambra
    FUNNELS_CUE_OPT_OUT: 'funnels-cue-opt-out-7301', // owner: @neilkakkar
    RETENTION_BREAKDOWN: 'retention-breakdown', // owner: @hazzadous
    WEB_PERFORMANCE: 'hackathon-apm', //owner: @pauldambra
    NEW_INSIGHT_COHORTS: '7569-insight-cohorts', // owner: @EDsCODE
    SMOOTHING_INTERVAL: 'smoothing-interval', // owner: @timgl
    BILLING_LIMIT: 'billing-limit', // owner: @timgl
    KAFKA_INSPECTOR: 'kafka-inspector', // owner: @yakkomajuri
    BILLING_LOCK_EVERYTHING: 'billing-lock-everything', // owner @timgl
    HISTORICAL_EXPORTS_V2: 'historical-exports-v2', // owner @macobo
    PERSON_ON_EVENTS_ENABLED: 'person-on-events-enabled', //owner: @EDsCODE
    REGION_SELECT: 'region-select', //owner: @kappa90
    INGESTION_WARNINGS_ENABLED: 'ingestion-warnings-enabled', // owner: @tiina303
    HOG_BOOK: 'hog-book', // owner: @pauldambra
    SESSION_RESET_ON_LOAD: 'session-reset-on-load', // owner: @benjackwhite
    FEEDBACK_BUTTON: 'feedback-button', // owner: @luke
    RECORDINGS_ON_FEATURE_FLAGS: 'recordings-on-feature-flags', // owner: @EDsCODE
    EXPOSURES_ON_FEATURE_FLAGS: 'exposures-on-feature-flags', // owner: @EDsCODE
    AUTO_ROLLBACK_FEATURE_FLAGS: 'auto-rollback-feature-flags', // owner: @EDsCODE
    ONBOARDING_V2_DEMO: 'onboarding-v2-demo', // owner: #team-growth
    FEATURE_FLAG_ROLLOUT_UX: 'feature-flag-rollout-ux', // owner: @neilkakkar
    ROLE_BASED_ACCESS: 'role-based-access', // owner: #team-experiments, @liyiy
    DATA_EXPLORATION_LIVE_EVENTS: 'data-exploration-live-events', // owner @mariusandra
    YULE_HOG: 'yule-hog', // owner: @benjackwhite
    HOGQL_EXPRESSIONS: 'hogql_expressions', // owner @mariusandra
    QUERY_RUNNING_TIME: 'query_running_time', // owner: @mariusandra
    DATA_EXPLORATION_INSIGHTS: 'data-exploration-insights', // owner @thmsobrmlr
    RECORDING_DEBUGGING: 'recording-debugging', // owner #team-session-recordings
    FF_JSON_PAYLOADS: 'ff-json-payloads', // owner @EDsCODE
    PERSON_GROUPS_PROPERTY_DEFINITIONS: 'person-groups-property-definitions', // owner: @macobo
    REQUIRE_EMAIL_VERIFICATION: 'require-email-verification', // owner: @raquelmsmith
    DATA_EXPLORATION_QUERIES_ON_DASHBOARDS: 'data-exploration-queries-on-dashboards', // owner: @pauldambra
    SAMPLING: 'sampling', // owner: @yakkomajuri
    DASHBOARD_TEMPLATES: 'dashboard-templates', // owner @pauldambra and @lharries
    TEMPLUKES: 'templukes', // owner: @pauldambra and @lharries
    RECORDINGS_V2_RECORDER: 'recordings-v2-recorder', // owner: #team-session-recordings
    POSTHOG_3000: 'posthog-3000', // owner: @Twixes
}

/** Which self-hosted plan's features are available with Cloud's "Standard" plan (aka card attached). */
export const POSTHOG_CLOUD_STANDARD_PLAN = LicensePlan.Scale
export const FEATURE_MINIMUM_PLAN: Partial<Record<AvailableFeature, LicensePlan>> = {
    [AvailableFeature.ZAPIER]: LicensePlan.Scale,
    [AvailableFeature.ORGANIZATIONS_PROJECTS]: LicensePlan.Scale,
    [AvailableFeature.GOOGLE_LOGIN]: LicensePlan.Scale,
    [AvailableFeature.DASHBOARD_COLLABORATION]: LicensePlan.Scale,
    [AvailableFeature.INGESTION_TAXONOMY]: LicensePlan.Scale,
    [AvailableFeature.PATHS_ADVANCED]: LicensePlan.Scale,
    [AvailableFeature.CORRELATION_ANALYSIS]: LicensePlan.Scale,
    [AvailableFeature.GROUP_ANALYTICS]: LicensePlan.Scale,
    [AvailableFeature.MULTIVARIATE_FLAGS]: LicensePlan.Scale,
    [AvailableFeature.EXPERIMENTATION]: LicensePlan.Scale,
    [AvailableFeature.TAGGING]: LicensePlan.Scale,
    [AvailableFeature.BEHAVIORAL_COHORT_FILTERING]: LicensePlan.Scale,
    [AvailableFeature.WHITE_LABELLING]: LicensePlan.Scale,
    [AvailableFeature.DASHBOARD_PERMISSIONING]: LicensePlan.Enterprise,
    [AvailableFeature.PROJECT_BASED_PERMISSIONING]: LicensePlan.Enterprise,
    [AvailableFeature.SAML]: LicensePlan.Enterprise,
    [AvailableFeature.SSO_ENFORCEMENT]: LicensePlan.Enterprise,
    [AvailableFeature.SUBSCRIPTIONS]: LicensePlan.Scale,
    [AvailableFeature.APP_METRICS]: LicensePlan.Scale,
    [AvailableFeature.RECORDINGS_PLAYLISTS]: LicensePlan.Scale,
    [AvailableFeature.ROLE_BASED_ACCESS]: LicensePlan.Enterprise,
    [AvailableFeature.RECORDINGS_FILE_EXPORT]: LicensePlan.Scale,
    [AvailableFeature.RECORDINGS_PERFORMANCE]: LicensePlan.Scale,
}

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

export const SSO_PROVIDER_NAMES: Record<SSOProviders, string> = {
    'google-oauth2': 'Google',
    github: 'GitHub',
    gitlab: 'GitLab',
    saml: 'single sign-on (SAML)',
}

// TODO: Remove UPGRADE_LINK, as the billing page is now universal
export const UPGRADE_LINK = (cloud?: boolean): { url: string; target?: '_blank' } =>
    cloud ? { url: urls.organizationBilling() } : { url: 'https://posthog.com/pricing', target: '_blank' }

export const DOMAIN_REGEX = /^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$/
export const SECURE_URL_REGEX = /^(?:http(s)?:\/\/)[\w.-]+(?:\.[\w\.-]+)+[\w\-\._~:\/?#[\]@!\$&'\(\)\*\+,;=.]+$/gi

export const CLOUD_HOSTNAMES = {
    [Region.US]: 'app.posthog.com',
    [Region.EU]: 'eu.posthog.com',
}

export const SESSION_RECORDINGS_PLAYLIST_FREE_COUNT = 5

// If _any_ item on a dashboard is older than this, dashboard is automatically reloaded
export const AUTO_REFRESH_DASHBOARD_THRESHOLD_HOURS = 20
