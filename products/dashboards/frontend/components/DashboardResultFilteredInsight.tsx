import { Query } from '~/queries/Query/Query'
import { DashboardFilter, HogQLVariable, InsightVizNode } from '~/queries/schema/schema-general'

import { getDashboardResultItemId } from '../dashboardResultFilters'

export function DashboardResultFilteredInsight({
    dashboardId,
    tileId,
    query,
    filtersOverride,
    variablesOverride,
    loadPriority,
}: {
    dashboardId: number
    tileId: number
    query: InsightVizNode
    filtersOverride?: DashboardFilter
    variablesOverride?: Record<string, HogQLVariable>
    loadPriority?: number
}): JSX.Element {
    return (
        <Query
            query={query}
            filtersOverride={filtersOverride}
            variablesOverride={variablesOverride}
            context={{
                dashboardResultMenu: true,
                dataVisualizationTableVirtualized: true,
                insightProps: {
                    dashboardItemId: getDashboardResultItemId(dashboardId, tileId),
                    query,
                    filtersOverride,
                    variablesOverride,
                    loadPriority,
                },
            }}
            readOnly
            embedded
        />
    )
}
