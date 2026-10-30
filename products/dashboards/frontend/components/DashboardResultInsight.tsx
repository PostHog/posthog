import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightModel } from '~/types'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'
import { getDashboardResultItemId } from '../dashboardResultFilters'

export function DashboardResultInsight({
    dashboardId,
    tileId,
    insight,
    insightProps,
    filtersOverride,
    variablesOverride,
    loadPriority,
}: {
    dashboardId: number
    tileId: number
    insight: InsightModel
    insightProps: InsightLogicProps
    filtersOverride?: DashboardFilter
    variablesOverride?: Record<string, HogQLVariable>
    loadPriority?: number
}): JSX.Element {
    const { targets, loadQueue } = useValues(dashboardResultFilterLogic({ dashboardId }))
    const filtered = targets[tileId]
    const query = filtered ?? insight.query
    // Dashboard responses already merge dashboard and tile overrides into the query.
    const effectiveFiltersOverride = filtered ? undefined : filtersOverride
    // Keep the saved query on metadata: matching it to the temporary query makes InsightViz treat it as cached data.
    const { result: _savedResult, ...metadata } = insight
    return (
        <Query
            query={query}
            cachedResults={filtered ? undefined : insight}
            filtersOverride={effectiveFiltersOverride}
            variablesOverride={variablesOverride}
            context={{
                dashboardResultMenu: true,
                loadQueue,
                insightProps: {
                    ...insightProps,
                    ...(filtered ? { doNotLoad: false, setQuery: undefined, dashboardId: undefined } : {}),
                    dashboardItemId: filtered ? getDashboardResultItemId(dashboardId, tileId) : insight.short_id,
                    cachedInsight: filtered ? metadata : insight,
                    query,
                    filtersOverride: effectiveFiltersOverride,
                    variablesOverride,
                    loadPriority,
                },
            }}
            readOnly
            embedded
        />
    )
}
