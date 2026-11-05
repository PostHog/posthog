import { deepEqual } from 'fast-equals'
import { useActions, useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { InsightModel } from '~/types'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { canSelectBIWorksheet, createBIDashboardSelection, getBIDashboardItemId } from './biDashboardCrossFilters'
import { getBIDashboardFilterLink } from './biDashboardFilterLinks'

export interface BIDashboardTileProps {
    dashboardId: number
    tileId: number
    insight: InsightModel
    query: BIVisualizationNode
    loadPriority?: number
}

export function BIDashboardTile({
    dashboardId,
    tileId,
    insight,
    query,
    loadPriority,
}: BIDashboardTileProps): JSX.Element {
    const { selection, targets, loadQueue } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    const { selectMark } = useActions(biDashboardCrossFilterLogic({ dashboardId }))
    const filtered = targets[tileId]
    const effectiveQuery = filtered ?? query
    const isActiveFilter = (record: Record<string, unknown>): boolean =>
        !!selection &&
        deepEqual(
            selection,
            createBIDashboardSelection(tileId, insight.name || 'Untitled worksheet', effectiveQuery, record)
        )
    return (
        <div className="flex h-full min-h-0 flex-col">
            <Query
                query={effectiveQuery}
                cachedResults={filtered ? undefined : insight}
                context={{
                    dashboardResultMenu: true,
                    loadQueue,
                    isBIMarkActiveFilter: isActiveFilter,
                    dataVisualizationTableVirtualized: true,
                    dataVisualizationTableVirtualizationCellThreshold: 100,
                    insightProps: {
                        dashboardItemId: getBIDashboardItemId(dashboardId, tileId, !!filtered),
                        cachedInsight: { ...insight, query: effectiveQuery, result: filtered ? null : insight.result },
                        query: effectiveQuery,
                        loadPriority,
                    },
                    onSelectBIMark: canSelectBIWorksheet(query)
                        ? (record) => selectMark(tileId, insight.name || 'Untitled worksheet', effectiveQuery, record)
                        : undefined,
                    getBIMarkDashboardUrl: (record) =>
                        getBIDashboardFilterLink(
                            window.location.href,
                            dashboardId,
                            tileId,
                            effectiveQuery.config,
                            record,
                            isActiveFilter(record)
                        ),
                }}
                readOnly
                embedded
            />
        </div>
    )
}
