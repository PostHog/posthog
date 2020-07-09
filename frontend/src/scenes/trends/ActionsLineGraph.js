import React, { useEffect } from 'react'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ACTIONS_LINE_GRAPH_STACKED, ACTIONS_LINE_GRAPH_CUMULATIVE_STACKED } from '~/lib/constants'

export function ActionsLineGraph({ dashboardItemId = null, color = 'white', filters: filtersParam }) {
    const { filters, results, resultsLoading } = useValues(trendsLogic({ dashboardItemId, filters: filtersParam }))
    const { loadResults, loadPeople } = useActions(trendsLogic({ dashboardItemId, filters: filtersParam }))

    const { people_action, people_day, ...otherFilters } = filters
    const isStacked =
        filters.display === ACTIONS_LINE_GRAPH_STACKED || filters.display === ACTIONS_LINE_GRAPH_CUMULATIVE_STACKED

    useEffect(() => {
        loadResults()
    }, [toParams(otherFilters)])
    return results && !resultsLoading ? (
        filters.session || results.reduce((total, item) => total + item.count, 0) > 0 ? (
            <LineGraph
                data-attr="trend-line-graph"
                type="line"
                isStacked={isStacked}
                color={color}
                datasets={results}
                labels={(results[0] && results[0].labels) || []}
                isInProgress={!filters.date_to}
                onClick={
                    dashboardItemId
                        ? null
                        : (point) => {
                              const { dataset, day } = point
                              loadPeople(dataset.action || 'session', dataset.label, day, dataset.breakdown_value)
                          }
                }
            />
        ) : (
            <p style={{ textAlign: 'center', paddingTop: '4rem' }}>
                We couldn't find any matching events. Try changing dates or pick another action or event.
            </p>
        )
    ) : (
        <Loading />
    )
}
