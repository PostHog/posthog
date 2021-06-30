import React, { useState } from 'react'
import { Loading } from '../../../lib/utils'
import { LineGraph } from '../../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { LineGraphEmptyState } from '../../insights/EmptyStates'
import { ACTIONS_BAR_CHART } from 'lib/constants'
import { ChartParams } from '~/types'
import { ViewType } from 'scenes/insights/insightLogic'
import { router } from 'kea-router'

export function ActionsLineGraph({
    dashboardItemId,
    color = 'white',
    filters: filtersParam,
    cachedResults,
    inSharedMode = false,
    view,
}: ChartParams): JSX.Element {
    const logic = trendsLogic({
        dashboardItemId,
        view: view || filtersParam?.insight,
        filters: filtersParam,
        cachedResults,
    })
    const { filters, indexedResults, resultsLoading, visibilityMap } = useValues(logic)
    const { loadPeople } = useActions(logic)
    const [{ fromItem }] = useState(router.values.hashParams)

    return indexedResults && !resultsLoading ? (
        indexedResults.filter((result) => result.count !== 0).length > 0 ? (
            <LineGraph
                data-attr="trend-line-graph"
                type={filters.insight === ViewType.LIFECYCLE || filters.display === ACTIONS_BAR_CHART ? 'bar' : 'line'}
                color={color}
                datasets={indexedResults}
                visibilityMap={visibilityMap}
                labels={(indexedResults[0] && indexedResults[0].labels) || []}
                isInProgress={!filters.date_to}
                dashboardItemId={dashboardItemId || fromItem}
                inSharedMode={inSharedMode}
                interval={filters.interval}
                onClick={
                    dashboardItemId
                        ? null
                        : (point) => {
                              const { dataset, day } = point
                              loadPeople(
                                  dataset.action || 'session',
                                  dataset.label,
                                  day,
                                  day,
                                  dataset.breakdown_value || dataset.status,
                                  true
                              )
                          }
                }
            />
        ) : (
            <LineGraphEmptyState color={color} isDashboard={!!dashboardItemId} />
        )
    ) : (
        <Loading />
    )
}
