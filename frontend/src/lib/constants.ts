export const ACTIONS_LINE_GRAPH_LINEAR = 'ActionsLineGraph'
export const ACTIONS_LINE_GRAPH_CUMULATIVE = 'ActionsLineGraphCumulative'
export const ACTIONS_TABLE = 'ActionsTable'
export const ACTIONS_PIE_CHART = 'ActionsPie'
export const RETENTION_TABLE = 'RetentionTable'
export const PATHS_VIZ = 'PathsViz'
export const FUNNEL_VIZ = 'FunnelViz'

export const STICKINESS = 'Stickiness'

export const LINEAR_CHART_LABEL = 'Linear'
export const CUMULATIVE_CHART_LABEL = 'Cumulative'
export const TABLE_LABEL = 'Table'
export const PIE_CHART_LABEL = 'Pie'

export enum OrganizationMembershipLevel {
    Member = 1,
    Admin = 8,
}

export const organizationMembershipLevelToName = new Map<number, string>([
    [OrganizationMembershipLevel.Member, 'member'],
    [OrganizationMembershipLevel.Admin, 'administrator'],
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
