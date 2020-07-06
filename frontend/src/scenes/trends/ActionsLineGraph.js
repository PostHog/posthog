import React, { useEffect, useState } from 'react'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { router } from 'kea-router'

export function ActionsLineGraph({ dashboardItemId = null, color = 'white', filters: filtersParam }) {
    const { filters, results, resultsLoading } = useValues(trendsLogic({ dashboardItemId, filters: filtersParam }))
    const { loadResults, loadPeople } = useActions(trendsLogic({ dashboardItemId, filters: filtersParam }))
    const { people_action, people_day, ...otherFilters } = filters
    const [{ fromItem }] = useState(router.values.hashParams)

    useEffect(() => {
        loadResults()
    }, [toParams(otherFilters)])
    return results && !resultsLoading ? (
        filters.session || results.reduce((total, item) => total + item.count, 0) > 0 ? (
            <LineGraph
                pageKey={'trends-annotations'}
                data-attr="trend-line-graph"
                type="line"
                color={color}
                datasets={results}
                labels={(results[0] && results[0].labels) || []}
                isInProgress={!filters.date_to}
                dashboardItemId={dashboardItemId || fromItem}
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
