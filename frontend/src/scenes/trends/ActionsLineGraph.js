import React, { useEffect } from 'react'
import api from '../../lib/api'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export function ActionsLineGraph() {
    const { filters, data } = useValues(trendsLogic)
    const { setData, showPeople } = useActions(trendsLogic)

    useEffect(() => {
        api.get('api/action/trends/?' + toParams(filters)).then(data => {
            // if still fetching for this filter
            if (filters === trendsLogic.values.filters) {
                setData(data)
            }
        })
    }, [filters])

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
            <p style={{ textAlign: 'center', marginTop: '4rem' }}>
                We couldn't find any matching actions.
            </p>
        )
    ) : (
        <Loading />
    )
}
