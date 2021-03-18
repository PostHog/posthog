import React, { useState } from 'react'
import { Loading } from '../../../lib/utils'
import { LineGraph } from '../../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { router } from 'kea-router'
import { LineGraphEmptyState } from '../../insights/EmptyStates'
import { ACTIONS_BAR_CHART, ShownAsValue } from 'lib/constants'
import { ChartParams } from '~/types'

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
        indexedResults.reduce((total, item) => total + item.count, 0) !== 0 ? (
            <LineGraph
                data-attr="trend-line-graph"
                type={
                    filters.shown_as === ShownAsValue.LIFECYCLE || filters.display === ACTIONS_BAR_CHART
                        ? 'bar'
                        : 'line'
                }
                color={color}
                datasets={indexedResults}
                visibilityMap={visibilityMap}
                labels={(indexedResults[0] && indexedResults[0].labels) || []}
                isInProgress={!filters.date_to}
                dashboardItemId={dashboardItemId || fromItem}
                inSharedMode={inSharedMode}
                onClick={
                    dashboardItemId
                        ? null
                        : (point) => {
                              const { dataset, day } = point
                              loadPeople(
                                  dataset.action || 'session',
                                  dataset.label,
                                  day,
                                  dataset.breakdown_value || dataset.status
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
