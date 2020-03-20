import React, { useEffect } from 'react'
import api from '../../lib/api'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export function ActionsLineGraph() {
    const { filters, data } = useValues(trendsLogic)
    const { loadData, showPeople } = useActions(trendsLogic)

    const { people_action, people_day, ...otherFilters } = filters

    useEffect(() => {
        loadData()
    }, [toParams(otherFilters)])

    return data ? (
        data[0] && data[0].labels ? (
            <LineGraph
                datasets={data}
                labels={data[0].labels}
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
