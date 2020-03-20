import React, { useEffect } from 'react'
import api from '../../lib/api'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export function ActionsLineGraph() {
    const { filters, results } = useValues(trendsLogic)
    const { loadResults, showPeople } = useActions(trendsLogic)

    const { people_action, people_day, ...otherFilters } = filters

    useEffect(() => {
        loadResults()
    }, [toParams(otherFilters)])

    return results ? (
        results[0] && results[0].labels ? (
            <LineGraph
                datasets={results}
                labels={results[0].labels}
                onClick={({ dataset: { action }, day }) => {
                    showPeople(action, day)
                }}
            />
        ) : (
            <p style={{ textAlign: 'center', marginTop: '4rem' }}>We couldn't find any matching actions.</p>
        )
    ) : (
        <Loading />
    )
}
