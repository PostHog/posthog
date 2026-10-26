import { Node, NodeKind } from '~/queries/schema/schema-general'
import { isNodeWithSource } from '~/queries/utils'
import { DashboardTile } from '~/types'

/** A filter control in the dashboard filter bar. */
export type DashboardControl =
    | 'dateRange'
    | 'interval'
    | 'properties'
    | 'breakdown'
    | 'testAccounts'
    | 'metricVariables'

export interface DashboardControlScope {
    /** Chart tiles that the control changes. */
    applies: number
    /** All chart tiles on the dashboard: insights, and widgets that follow dashboard filters. */
    total: number
}

const ALL_CONTROLS: DashboardControl[] = [
    'dateRange',
    'interval',
    'properties',
    'breakdown',
    'testAccounts',
    'metricVariables',
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
    [NodeKind.MetricsQuery]: ['dateRange', 'metricVariables'],
    [NodeKind.MetricsHistogramQuery]: ['dateRange', 'metricVariables'],
}

export function dashboardControlsForQuery(query: Node | null | undefined): DashboardControl[] {
    const source = isNodeWithSource(query) ? query.source : query
    return (source?.kind && CONTROLS_BY_QUERY_KIND[source.kind as NodeKind]) || DEFAULT_CONTROLS
}

/** `widgetControls` holds the controls of each widget tile that follows dashboard filters. */
export function getDashboardControlScopes(
    insightTiles: DashboardTile[],
    widgetControls: DashboardControl[][] = []
): Record<DashboardControl, DashboardControlScope> {
    const tileControls = [
        ...insightTiles.map((tile) => dashboardControlsForQuery(tile.insight?.query)),
        ...widgetControls,
    ]
    const scopes = Object.fromEntries(
        ALL_CONTROLS.map((control) => [control, { applies: 0, total: tileControls.length }])
    ) as Record<DashboardControl, DashboardControlScope>
    for (const controls of tileControls) {
        for (const control of controls) {
            scopes[control].applies++
        }
    }
    return scopes
}

/** Text for a control that changes only some of the charts. Null when it changes all or none of them. */
export function dashboardControlScopeText(scope: DashboardControlScope): string | null {
    if (scope.applies === 0 || scope.applies === scope.total) {
        return null
    }
    return `Applies to ${scope.applies} of ${scope.total} charts`
}

/** A control that changes no chart is hidden, unless it has a value that the user must be able to clear. */
export function isDashboardControlHidden(scope: DashboardControlScope, hasValue: boolean): boolean {
    return scope.total > 0 && scope.applies === 0 && !hasValue
}
