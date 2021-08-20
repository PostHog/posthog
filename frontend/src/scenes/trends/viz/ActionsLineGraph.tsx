import React, { useState } from 'react'
import { Loading } from '../../../lib/utils'
import { LineGraph } from '../../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { LineGraphEmptyState } from '../../insights/EmptyStates'
import { ACTIONS_BAR_CHART } from 'lib/constants'
import { ChartParams } from '~/types'
import { ViewType } from '~/types'
import { router } from 'kea-router'
import { personsModalLogic } from '../personsModalLogic'

export function ActionsLineGraph({
    dashboardItemId,
    color = 'white',
    filters: filtersParam,
    cachedResults,
    inSharedMode = false,
    showPersonsModal = true,
    view,
}: ChartParams): JSX.Element {
    const logic = trendsLogic({
        dashboardItemId,
        view: view || filtersParam?.insight,
        filters: filtersParam,
        cachedResults,
    })
    const { filters, indexedResults, resultsLoading, visibilityMap } = useValues(logic)
    const { loadPeople } = useActions(personsModalLogic)
    const [{ fromItem }] = useState(router.values.hashParams)

    return indexedResults && indexedResults[0]?.data && !resultsLoading ? (
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
                showPersonsModal={showPersonsModal}
                tooltipPreferAltTitle={filters.insight === ViewType.STICKINESS}
                onClick={
                    dashboardItemId
                        ? null
                        : (point) => {
                              const { dataset, day } = point
                              loadPeople({
                                  action: dataset.action || 'session',
                                  label: dataset.label,
                                  date_from: day,
                                  date_to: day,
                                  filters: filters,
                                  breakdown_value:
                                      dataset.breakdown_value === undefined ? dataset.status : dataset.breakdown_value,
                                  saveOriginal: true,
                              })
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
