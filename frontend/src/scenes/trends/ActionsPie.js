import React, { useEffect, useState } from 'react'
import { Loading } from 'lib/utils'
import { LineGraph } from './LineGraph'
import { getChartColors } from 'lib/colors'
import { useValues, useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export function ActionsPie({ dashboardItemId, filters: filtersParam, color }) {
    const [data, setData] = useState(null)
    const [total, setTotal] = useState(0)

    const { filters, results, resultsLoading } = useValues(trendsLogic({ dashboardItemId, filters: filtersParam }))
    const { loadResults } = useActions(trendsLogic({ dashboardItemId, filters: filtersParam }))

    function updateData() {
        const data = results
        data.sort((a, b) => b.count - a.count)

        const colorList = getChartColors(color)

        setData([
            {
                labels: data.map((item) => item.label),
                data: data.map((item) => item.data && item.data.reduce((prev, d) => prev + d, 0)),
                backgroundColor: colorList,
                hoverBackgroundColor: colorList,
                hoverBorderColor: colorList,
                borderColor: colorList,
                hoverBorderWidth: 10,
                borderWidth: 1,
            },
        ])
        setTotal(data.reduce((prev, item) => prev + item.count, 0))
    }

    useEffect(() => {
        loadResults()
    }, [filters, color])

    useEffect(() => {
        updateData()
    }, [results])

    return data && !resultsLoading ? (
        data[0] && data[0].labels ? (
            <div
                style={{
                    position: 'absolute',
                    width: '100%',
                    height: '100%',
                }}
            >
                <h1
                    style={{
                        position: 'absolute',
                        margin: '0 auto',
                        left: '50%',
                        top: '50%',
                        fontSize: '3rem',
                        zIndex: 2,
                        pointerEvents: 'none',
                    }}
                >
                    <div style={{ marginLeft: '-50%', marginTop: -35 }}>{total}</div>
                </h1>
                <LineGraph
                    data-attr="trend-pie-graph"
                    color={color}
                    type="doughnut"
                    datasets={data}
                    labels={data[0].labels}
                />
            </div>
        ) : (
            <p style={{ textAlign: 'center', marginTop: '4rem' }}>We couldn't find any matching actions.</p>
        )
    ) : (
        <Loading />
    )
}
