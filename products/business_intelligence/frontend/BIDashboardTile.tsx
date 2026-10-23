import { deepEqual } from 'fast-equals'
import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { HogQLVariable } from '~/queries/schema/schema-general'
import { InsightModel } from '~/types'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { canSelectBIWorksheet, createBIDashboardSelection, getBIDashboardItemId } from './biDashboardCrossFilters'
import { getBIDashboardFilterLink } from './biDashboardFilterLinks'
import { getBIDrillSelection } from './biDrilldown'

export interface BIDashboardTileProps {
    dashboardId: number
    tileId: number
    insight: InsightModel
    query: BIVisualizationNode
    variablesOverride?: Record<string, HogQLVariable>
    loadPriority?: number
}

export function BIDashboardTile({
    dashboardId,
    tileId,
    insight,
    query,
    variablesOverride,
    loadPriority,
}: BIDashboardTileProps): JSX.Element {
    const { selection, targets } = useValues(biDashboardCrossFilterLogic({ dashboardId }))
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
            {selection && (
                <div className="px-3 pt-1">
                    <LemonTag type={filtered ? 'highlight' : 'default'}>
                        {filtered
                            ? 'Filtered by selection'
                            : selection.tileId === tileId
                              ? 'Filter source'
                              : 'Not filtered'}
                    </LemonTag>
                </div>
            )}
            <Query
                query={effectiveQuery}
                cachedResults={filtered ? undefined : insight}
                variablesOverride={variablesOverride}
                context={{
                    dashboardResultMenu: true,
                    dashboardFilterActive: !!selection,
                    isBIMarkActiveFilter: isActiveFilter,
                    dataVisualizationTableVirtualized: true,
                    isBIMarkSelected:
                        selection?.tileId === tileId
                            ? (record) => {
                                  const candidate = getBIDrillSelection(query.config, record)
                                  return (
                                      !candidate.previous &&
                                      selection.selection.filters.every((filter) =>
                                          candidate.filters.some((other) => deepEqual(filter, other))
                                      )
                                  )
                              }
                            : undefined,
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
