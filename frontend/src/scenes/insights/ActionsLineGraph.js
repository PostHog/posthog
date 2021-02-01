import React, { useState } from 'react'
import { Loading } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/insights/trendsLogic'
import { router } from 'kea-router'
import { LineGraphEmptyState } from './EmptyStates'
import { ACTIONS_BAR_CHART, LIFECYCLE } from 'lib/constants'

export function ActionsLineGraph({
    dashboardItemId = null,
    color = 'white',
    filters: filtersParam,
    cachedResults,
    inSharedMode,
    view,
}) {
    const logic = trendsLogic({
        dashboardItemId,
        view: view || filtersParam.insight,
        filters: filtersParam,
        cachedResults,
    })
    const { filters, results, resultsLoading } = useValues(logic)
    const { loadPeople } = useActions(logic)

    const { people_action, people_day, ...otherFilters } = filters // eslint-disable-line
    const [{ fromItem }] = useState(router.values.hashParams)

    return results && !resultsLoading ? (
        results.reduce((total, item) => total + item.count, 0) !== 0 ? (
            <LineGraph
                pageKey={'trends-annotations'}
                data-attr="trend-line-graph"
                type={filters.shown_as === LIFECYCLE || filters.display === ACTIONS_BAR_CHART ? 'bar' : 'line'}
                color={color}
                datasets={results}
                labels={(results[0] && results[0].labels) || []}
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
            <LineGraphEmptyState color={color} />
        )
    ) : (
        <Loading />
    )
}
