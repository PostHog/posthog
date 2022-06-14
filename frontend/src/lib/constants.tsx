import { urls } from 'scenes/urls'
import { AnnotationScope, AvailableFeature, ChartDisplayType, LicensePlan, SSOProviders } from '../types'

// Sync with backend NON_TIME_SERIES_DISPLAY_TYPES
export const NON_TIME_SERIES_DISPLAY_TYPES = [
    ChartDisplayType.ActionsTable,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.WorldMap,
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

export const annotationScopeToName = new Map<string, string>([
    [AnnotationScope.Insight, 'insight'],
    [AnnotationScope.Project, 'project'],
    [AnnotationScope.Organization, 'organization'],
])

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
export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = ['email', 'name', 'username']

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

// Properties constants
export const PROPERTY_MATH_TYPE = 'property'
export const EVENT_MATH_TYPE = 'event'

export const WEBHOOK_SERVICES: Record<string, string> = {
    Slack: 'slack.com',
    Discord: 'discord.com',
    Teams: 'office.com',
}

export const FEATURE_FLAGS = {
    // Cloud-only
    CLOUD_ANNOUNCEMENT: 'cloud-announcement',
    NPS_PROMPT: '4562-nps', // owner: @marcushyett-ph
    // Experiments / beta features
    NEW_PATHS_UI_EDGE_WEIGHTS: 'new-paths-ui-edge-weights', // owner: @neilkakkar
    BREAKDOWN_BY_MULTIPLE_PROPERTIES: '938-breakdown-by-multiple-properties', // owner: @pauldambra
    FUNNELS_CUE_OPT_OUT: 'funnels-cue-opt-out-7301', // owner: @neilkakkar
    RETENTION_BREAKDOWN: 'retention-breakdown', // owner: @hazzadous
    INSIGHT_LEGENDS: 'insight-legends', // owner: @alexkim205
    RECORDINGS_IN_INSIGHTS: 'recordings-in-insights', // owner: @rcmarron
    WEB_PERFORMANCE: 'hackathon-apm', //owner: @pauldambra
    NEW_INSIGHT_COHORTS: '7569-insight-cohorts', // owner: @EDsCODE
    INVITE_TEAMMATES_BANNER: 'invite-teammates-prompt', // owner: @marcushyett-ph
    DASHBOARD_PERMISSIONS: 'dashboard-permissions', // owner: @Twixes
    SESSION_CONSOLE: 'session-recording-console', // owner: @timgl
    SMOOTHING_INTERVAL: 'smoothing-interval', // owner: @timgl
    BILLING_LIMIT: 'billing-limit', // owner: @timgl
    KAFKA_INSPECTOR: 'kafka-inspector', // owner: @yakkomajuri
    INSIGHT_EDITOR_PANELS: '8929-insight-editor-panels', // owner: @mariusandra
    MULTI_DASHBOARD_INSIGHTS: 'multi-dashboard-insights', // owner: @pauldambra
    INSIGHT_ACTIVITY_LOG: '8545-insight-activity-log', // owner: @pauldambra
    COHORT_FILTERS: 'cohort-filters', // owner: @edscode
    FRONTEND_APPS: '9618-frontend-apps', // owner: @mariusandra
    PROPERTY_FILTER_ON_DASHBOARD: 'property-filter-on-dashboard', // owner: @edscode
    EXPORT_DASHBOARD_INSIGHTS: 'export-dashboard-insights', // owner: @benjackwhite
    ONBOARDING_1_5: 'onboarding-1_5', // owner: @liyiy
    BREAKDOWN_ATTRIBUTION: 'breakdown-attribution', // owner: @neilkakkar
}

/** Which self-hosted plan's features are available with Cloud's "Standard" plan (aka card attached). */
export const POSTHOG_CLOUD_STANDARD_PLAN = LicensePlan.Scale
export const FEATURE_MINIMUM_PLAN: Record<AvailableFeature, LicensePlan> = {
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
}

export const ENTITY_MATCH_TYPE = 'entities'
export const PROPERTY_MATCH_TYPE = 'properties'

export enum FunnelLayout {
    horizontal = 'horizontal',
    vertical = 'vertical',
}

export const BIN_COUNT_AUTO = 'auto'

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

// TODO: Support checking minimum plan required for specific feature and highlight the relevant plan in the
// pricing page (or billing page). Requires updating the pricing page to support this highlighting first.
export const UPGRADE_LINK = (cloud?: boolean): { url: string; target?: '_blank' } =>
    cloud ? { url: urls.organizationBilling() } : { url: 'https://posthog.com/pricing', target: '_blank' }

export const DOMAIN_REGEX = /^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$/
export const SECURE_URL_REGEX = /^(?:http(s)?:\/\/)[\w.-]+(?:\.[\w\.-]+)+[\w\-\._~:\/?#[\]@!\$&'\(\)\*\+,;=.]+$/gi
