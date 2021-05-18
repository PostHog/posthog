import './ActionsPie.scss'

import React, { useState, useEffect } from 'react'
import { Loading, maybeAddCommasToInteger } from 'lib/utils'
import { LineGraph } from '../../insights/LineGraph'
import { getChartColors } from 'lib/colors'
import { useValues, useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ChartParams, TrendResultWithAggregate } from '~/types'

export function ActionsPie({
    dashboardItemId,
    view,
    filters: filtersParam,
    color = 'white',
    cachedResults,
    inSharedMode,
}: ChartParams): JSX.Element {
    const [data, setData] = useState<Record<string, any>[] | null>(null)
    const [total, setTotal] = useState(0)
    const logic = trendsLogic({ dashboardItemId, view, filters: filtersParam, cachedResults })
    const { loadPeople } = useActions(logic)
    const { results, resultsLoading } = useValues(logic)

    function updateData(): void {
        const _data = results as TrendResultWithAggregate[]
        _data.sort((a, b) => b.aggregated_value - a.aggregated_value)
        const days = results.length > 0 ? results[0].days : []

        const colorList = getChartColors(color)

        setData([
            {
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                actions: _data.map((item) => item.action),
                days,
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
        if (results) {
            updateData()
        }
    }, [results, color])

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
                        inSharedMode={inSharedMode}
                        dashboardItemId={dashboardItemId}
                        onClick={(point) => {
                            const { dataset } = point
                            const action = dataset.actions[point.index]
                            const label = dataset.labels[point.index]
                            const date_from = dataset.days[0]
                            const date_to = dataset.days[dataset.days.length - 1]
                            loadPeople(action, label, date_from, date_to, null)
                        }}
                    />
                </div>
                <h1>
                    <span className="label">Total: </span>
                    {maybeAddCommasToInteger(total)}
                </h1>
            </div>
        ) : (
            <p style={{ textAlign: 'center', marginTop: '4rem' }}>We couldn't find any matching actions.</p>
        )
    ) : (
        <Loading />
    )
}
