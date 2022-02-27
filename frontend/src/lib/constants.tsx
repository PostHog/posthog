import { AnnotationScope, AvailableFeature, LicensePlan } from '../types'

// Sync these with the ChartDisplayType enum in types.ts
// ... and remove once all files have migrated to TypeScript
export const ACTIONS_LINE_GRAPH_LINEAR = 'ActionsLineGraph'
export const ACTIONS_LINE_GRAPH_CUMULATIVE = 'ActionsLineGraphCumulative'
export const ACTIONS_TABLE = 'ActionsTable'
export const ACTIONS_PIE_CHART = 'ActionsPie'
export const ACTIONS_BAR_CHART = 'ActionsBar'
export const ACTIONS_BAR_CHART_VALUE = 'ActionsBarValue'
export const PATHS_VIZ = 'PathsViz'
export const FUNNEL_VIZ = 'FunnelViz'

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

export const PERSON_DISTINCT_ID_MAX_SIZE = 3

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
    NPS_PROMPT: '4562-nps', // owner: @paolodamico
    // Experiments / beta features
    INGESTION_GRID: 'ingestion-grid-exp-3', // owner: @kpthatsme
    DIVE_DASHBOARDS: 'hackathon-dive-dashboards', // owner: @tiina303
    NEW_PATHS_UI_EDGE_WEIGHTS: 'new-paths-ui-edge-weights', // owner: @neilkakkar
    BREAKDOWN_BY_MULTIPLE_PROPERTIES: '938-breakdown-by-multiple-properties', // owner: @pauldambra
    FUNNELS_CUE_OPT_OUT: 'funnels-cue-opt-out-7301', // owner: @paolodamico
    FUNNELS_CUE_ENABLED: 'funnels-cue-enabled', // owner: @paolodamico
    EXPERIMENTATION: 'experimentation', // owner: @neilkakkar
    RETENTION_BREAKDOWN: 'retention-breakdown', // owner: @hazzadous
    STALE_EVENTS: 'stale-events', // owner: @paolodamico
    INSIGHT_LEGENDS: 'insight-legends', // owner: @alexkim205
    LINE_GRAPH_V2: 'line-graph-v2', // owner @alexkim205
    UNSEEN_EVENT_PROPERTIES: 'unseen-event-properties', // owner: @mariusandra
    QUERY_EVENTS_BY_DATETIME: '6619-query-events-by-date', // owner @pauldambra
    MULTI_POINT_PERSON_MODAL: '7590-multi-point-person-modal', // owner: @paolodamico
    RECORDINGS_IN_INSIGHTS: 'recordings-in-insights', // owner: @rcmarron
    EXPERIMENT_CORRELATION_DISCOVERY: 'experiment-correlation-discovery', // owner: @neilkakkar
    PATHS_ADVANCED_EXPERIMENT: 'paths-advanced-2101', // owner: @paolodamico; `control`, `direct` (A), `no-advanced` (B)
    WEB_PERFORMANCE: 'hackathon-apm', //owner @pauldambra
    NEW_INSIGHT_COHORTS: '7569-insight-cohorts',
    COLLABORATIONS_TAXONOMY: 'collaborations-taxonomy', // owner: @alexkim205
    INVITE_TEAMMATES_BANNER: 'invite-teammates-prompt', // owner: @marcushyett-ph
    EXPERIMENTS_SECONDARY_METRICS: 'experiments-secondary-metrics',
    RECORDINGS_FILTER_EXPERIMENT: 'recording-filters-experiment', // owner: @rcmarron
    DASHBOARD_PERMISSIONS: 'dashboard-permissions', // owner: @Twixes
    AND_OR_FILTERING: 'and-or-filtering', // owner: @edscode
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
    [AvailableFeature.DASHBOARD_PERMISSIONING]: LicensePlan.Enterprise,
    [AvailableFeature.PROJECT_BASED_PERMISSIONING]: LicensePlan.Enterprise,
    [AvailableFeature.SAML]: LicensePlan.Enterprise,
}

export const ENTITY_MATCH_TYPE = 'entities'
export const PROPERTY_MATCH_TYPE = 'properties'

export enum FunnelLayout {
    horizontal = 'horizontal',
    vertical = 'vertical',
}

export const BinCountAuto = 'auto'

export const ERROR_MESSAGES: Record<string, string> = {
    no_new_organizations:
        'Your email address is not associated with an account. Please ask your administrator for an invite.',
}

// Cohort types
export const COHORT_STATIC = 'static'
export const COHORT_DYNAMIC = 'dynamic'

/**
 * Mock Node.js `process`, which is required by VFile that is used by ReactMarkdown.
 * See https://github.com/remarkjs/react-markdown/issues/339.
 */
export const MOCK_NODE_PROCESS = { cwd: () => '', env: {} } as unknown as NodeJS.Process
