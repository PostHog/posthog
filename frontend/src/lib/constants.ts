export const ACTIONS_LINE_GRAPH_LINEAR = 'ActionsLineGraph'
export const ACTIONS_LINE_GRAPH_CUMULATIVE = 'ActionsLineGraphCumulative'
export const ACTIONS_TABLE = 'ActionsTable'
export const ACTIONS_PIE_CHART = 'ActionsPie'
export const ACTIONS_BAR_CHART = 'ActionsBar'
export const PATHS_VIZ = 'PathsViz'
export const FUNNEL_VIZ = 'FunnelViz'

export const VOLUME = 'Volume'
export const STICKINESS = 'Stickiness'
export const LIFECYCLE = 'Lifecycle'

export enum OrganizationMembershipLevel {
    Member = 1,
    Admin = 8,
    Owner = 15,
}

export const organizationMembershipLevelToName = new Map<number, string>([
    [OrganizationMembershipLevel.Member, 'member'],
    [OrganizationMembershipLevel.Admin, 'administrator'],
    [OrganizationMembershipLevel.Owner, 'owner'],
])

export enum AnnotationScope {
    DashboardItem = 'dashboard_item',
    Project = 'project',
    Organization = 'organization',
}

export const annotationScopeToName = new Map<string, string>([
    [AnnotationScope.DashboardItem, 'dashboard item'],
    [AnnotationScope.Project, 'project'],
    [AnnotationScope.Organization, 'organization'],
])

export const PERSON_DISTINCT_ID_MAX_SIZE = 3

export const PAGEVIEW = '$pageview'
export const AUTOCAPTURE = '$autocapture'
export const SCREEN = '$screen'
export const CUSTOM_EVENT = 'custom_event'

export const ACTION_TYPE = 'action_type'
export const EVENT_TYPE = 'event_type'

export enum ShownAsValue {
    VOLUME = 'Volume',
    STICKINESS = 'Stickiness',
    LIFECYCLE = 'Lifecycle',
}
