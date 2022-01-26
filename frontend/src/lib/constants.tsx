import { AnnotationScope } from '../types'

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
    FEEDBACK_CALL_CTA: 'feedback-call-cta', // owner: @paolodamico
    // Experiments / beta features
    INGESTION_GRID: 'ingestion-grid-exp-3', // owner: @kpthatsme
    FUNNEL_HORIZONTAL_UI: '5730-funnel-horizontal-ui', // owner: @alexkim205
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
    DASHBOARD_REDESIGN: 'dashboard-redesign', // owner: @Twixes
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
