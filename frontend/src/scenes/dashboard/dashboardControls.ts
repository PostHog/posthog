import { Node, NodeKind } from '~/queries/schema/schema-general'
import { isNodeWithSource } from '~/queries/utils'
import { DashboardTile } from '~/types'

/** A filter control in the dashboard filter bar. */
export type DashboardControl = 'dateRange' | 'interval' | 'properties' | 'breakdown' | 'testAccounts' | 'metricLabels'

export interface DashboardControlScope {
    /** Insight tiles that the control changes. */
    applies: number
    /** All insight tiles on the dashboard. */
    total: number
}

const ALL_CONTROLS: DashboardControl[] = [
    'dateRange',
    'interval',
    'properties',
    'breakdown',
    'testAccounts',
    'metricLabels',
]

// Matches what each query runner's `apply_dashboard_filters` changes. A kind that is not listed keeps
// the controls every tile had before tiles declared their controls.
const DEFAULT_CONTROLS: DashboardControl[] = ['dateRange', 'interval', 'properties', 'breakdown', 'testAccounts']

const CONTROLS_BY_QUERY_KIND: Partial<Record<NodeKind, DashboardControl[]>> = {
    [NodeKind.RetentionQuery]: ['dateRange', 'properties', 'breakdown', 'testAccounts'],
    [NodeKind.PathsQuery]: ['dateRange', 'properties', 'testAccounts'],
    [NodeKind.PathsV2Query]: ['dateRange', 'properties', 'testAccounts'],
    [NodeKind.StickinessQuery]: ['dateRange', 'interval', 'properties', 'testAccounts'],
    [NodeKind.LifecycleQuery]: ['dateRange', 'interval', 'properties', 'testAccounts'],
    [NodeKind.CalendarHeatmapQuery]: ['dateRange', 'interval', 'properties', 'testAccounts'],
    [NodeKind.MetricsQuery]: ['dateRange', 'metricLabels'],
    [NodeKind.MetricsHistogramQuery]: ['dateRange', 'metricLabels'],
}

export function dashboardControlsForQuery(query: Node | null | undefined): DashboardControl[] {
    const source = isNodeWithSource(query) ? query.source : query
    return (source?.kind && CONTROLS_BY_QUERY_KIND[source.kind as NodeKind]) || DEFAULT_CONTROLS
}

export function getDashboardControlScopes(
    insightTiles: DashboardTile[]
): Record<DashboardControl, DashboardControlScope> {
    const queries = insightTiles.map((tile) => tile.insight?.query)
    const scopes = Object.fromEntries(
        ALL_CONTROLS.map((control) => [control, { applies: 0, total: queries.length }])
    ) as Record<DashboardControl, DashboardControlScope>
    for (const query of queries) {
        for (const control of dashboardControlsForQuery(query)) {
            scopes[control].applies++
        }
    }
    return scopes
}

/** Text for a control that changes only some of the insights. Null when it changes all or none of them. */
export function dashboardControlScopeText(scope: DashboardControlScope): string | null {
    if (scope.applies === 0 || scope.applies === scope.total) {
        return null
    }
    return `Applies to ${scope.applies} of ${scope.total} insights`
}

/** A control that changes no insight is hidden, unless it has a value that the user must be able to clear. */
export function isDashboardControlHidden(scope: DashboardControlScope, hasValue: boolean): boolean {
    return scope.total > 0 && scope.applies === 0 && !hasValue
}
