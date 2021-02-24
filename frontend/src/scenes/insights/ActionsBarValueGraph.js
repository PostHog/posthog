import './ActionsPie.scss'

import React, { useState, useEffect } from 'react'
import { Loading } from 'lib/utils'
import { LineGraph } from './LineGraph'
import { getChartColors } from 'lib/colors'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/insights/trendsLogic'
import { LineGraphEmptyState } from './EmptyStates'

export function ActionsBarValueGraph({ dashboardItemId, view, filters: filtersParam, color, cachedResults }) {
    const [data, setData] = useState(null)
    const [total, setTotal] = useState(0)
    const logic = trendsLogic({ dashboardItemId, view, filters: filtersParam, cachedResults })
    const { results, resultsLoading } = useValues(logic)

    console.log({ data })

    function updateData() {
        const _data = [...results]
        _data.sort((a, b) => b.aggregated_value - a.aggregated_value)

        const colorList = getChartColors(color)

        setData([
            {
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                backgroundColor: colorList,
                hoverBackgroundColor: colorList,
                hoverBorderColor: colorList,
                borderColor: colorList,
                hoverBorderWidth: 10,
                borderWidth: 1,
            },
        ])
        setTotal(_data.reduce((prev, item) => prev + item.aggregated_value, 0))
    }

    useEffect(() => {
        updateData()
    }, [results, color])

    return data && !resultsLoading ? (
        total > 0 ? (
            <LineGraph
                pageKey={'trends-annotations'}
                data-attr="trend-bar-value-graph"
                type={'bar'}
                color={color}
                datasets={data}
                labels={data[0].labels}
                dashboardItemId={dashboardItemId}
            />
        ) : (
            <LineGraphEmptyState color={color} />
        )
    ) : (
        <Loading />
    )
}
