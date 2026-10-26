import { deepEqual } from 'fast-equals'
import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { Query } from '~/queries/Query/Query'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { InsightModel } from '~/types'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { canSelectBIWorksheet, createBIDashboardSelection, getBIDashboardItemId } from './biDashboardCrossFilters'
import { getBIDashboardFilterLink } from './biDashboardFilterLinks'

export interface BIDashboardTileProps {
    dashboardId: number
    tileId: number
    insight: InsightModel
    query: BIVisualizationNode
    filtersOverride?: DashboardFilter | null
    variablesOverride?: Record<string, HogQLVariable>
    loadPriority?: number
}

export function BIDashboardTile({
    dashboardId,
    tileId,
    insight,
    query,
    filtersOverride,
    variablesOverride,
    loadPriority,
}: BIDashboardTileProps): JSX.Element {
    const { selection, targets } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
    const { selectMark } = useActions(biDashboardCrossFilterLogic({ dashboardId }))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const filtered = targets[tileId]
    const effectiveQuery = filtered ?? query
    const isActiveFilter = (record: Record<string, unknown>): boolean =>
        !!selection &&
        deepEqual(
            selection,
            createBIDashboardSelection(tileId, insight.name || 'Untitled worksheet', effectiveQuery, record)
        )
    const filterStatus = filtered
        ? 'Filtered by selection'
        : selection?.tileId === tileId
          ? 'Filter source'
          : 'Not filtered'
    return (
        <div className="flex h-full min-h-0 flex-col">
            {selection && (
                <div className="px-3 pt-1">
                    {todayRailNav ? (
                        <Badge>{filterStatus}</Badge>
                    ) : (
                        <LemonTag type={filtered ? 'highlight' : 'default'}>{filterStatus}</LemonTag>
                    )}
                </div>
            )}
            <Query
                query={effectiveQuery}
                cachedResults={filtered ? undefined : insight}
                filtersOverride={filtersOverride}
                variablesOverride={variablesOverride}
                context={{
                    dashboardResultMenu: true,
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
