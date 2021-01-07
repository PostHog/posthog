import './ActionsPie.scss'

import React, { useState, useEffect } from 'react'
import { Loading } from 'lib/utils'
import { LineGraph } from './LineGraph'
import { getChartColors } from 'lib/colors'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/insights/trendsLogic'

export function ActionsPie({ dashboardItemId, view, filters: filtersParam, color, cachedResults }) {
    const [data, setData] = useState(null)
    const [total, setTotal] = useState(0)
    const logic = trendsLogic({ dashboardItemId, view, filters: filtersParam, cachedResults })
    const { results, resultsLoading } = useValues(logic)

    function updateData() {
        const data = results
        data.sort((a, b) => b.aggregated_value - a.aggregated_value)

        const colorList = getChartColors(color)

        setData([
            {
                labels: data.map((item) => item.label),
                data: data.map((item) => item.aggregated_value),
                backgroundColor: colorList,
                hoverBackgroundColor: colorList,
                hoverBorderColor: colorList,
                borderColor: colorList,
                hoverBorderWidth: 10,
                borderWidth: 1,
            },
        ])
        setTotal(data.reduce((prev, item) => prev + item.aggregated_value, 0))
    }

    useEffect(() => {
        updateData()
    }, [results])

    return data && !resultsLoading ? (
        data[0] && data[0].labels ? (
            <div className="actions-pie-component">
                <div className="pie-chart">
                    <LineGraph
                        data-attr="trend-pie-graph"
                        color={color}
                        type="doughnut"
                        datasets={data}
                        labels={data[0].labels}
                    />
                </div>
                <h1>
                    <span className="label">Total: </span>
                    {total}
                </h1>
            </div>
        ) : (
            <p style={{ textAlign: 'center', marginTop: '4rem' }}>We couldn't find any matching actions.</p>
        )
    ) : (
        <Loading />
    )
}
