import React, { useEffect } from 'react'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export function ActionsLineGraph({ dashboardItemId = null, color = 'white', filters: filtersParam }) {
    const { filters, results } = useValues(trendsLogic({ dashboardItemId, filters: filtersParam }))
    const { loadResults, loadPeople } = useActions(trendsLogic({ dashboardItemId, filters: filtersParam }))

    const { people_action, people_day, ...otherFilters } = filters

    useEffect(() => {
        loadResults()
    }, [toParams(otherFilters)])
    return results ? (
        filters.session || results.reduce((total, item) => total + item.count, 0) > 0 ? (
            <LineGraph
                data-attr="trend-line-graph"
                type="line"
                color={color}
                datasets={results}
                labels={(results[0] && results[0].labels) || []}
                isInProgress={!filters.date_to}
                onClick={
                    dashboardItemId
                        ? null
                        : point => {
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
