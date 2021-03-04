import React, { useState, useEffect } from 'react'
import { Loading } from 'lib/utils'
import { LineGraph } from '../../insights/LineGraph'
import { getChartColors } from 'lib/colors'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { LineGraphEmptyState } from '../../insights/EmptyStates'
import { ViewType } from 'scenes/insights/insightLogic'
import { TrendResultWithAggregate } from '~/types'

interface Props {
    dashboardItemId?: number | null
    view: ViewType
    color?: string
    inSharedMode?: boolean | null
    filters?: Record<string, unknown>
    cachedResults?: any
}

type DataSet = any

export function ActionsBarValueGraph({
    dashboardItemId = null,
    view,
    filters: filtersParam,
    color = 'white',
    cachedResults,
}: Props): JSX.Element {
    const [data, setData] = useState<DataSet[] | null>(null)
    const [total, setTotal] = useState(0)
    const logic = trendsLogic({ dashboardItemId, view, filters: filtersParam, cachedResults })
    const { results, resultsLoading } = useValues(logic)

    function updateData(): void {
        const _data = [...results] as TrendResultWithAggregate[]
        _data.sort((a, b) => b.aggregated_value - a.aggregated_value)

        const colorList = getChartColors(color)

        setData([
            {
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                actions: _data.map((item) => item.action),
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

    useEffect(updateData, [results, color])

    return data && !resultsLoading ? (
        total > 0 ? (
            <LineGraph
                data-attr="trend-bar-value-graph"
                type={'horizontalBar'}
                color={color}
                datasets={data}
                labels={data[0].labels}
                dashboardItemId={dashboardItemId}
                totalValue={total}
            />
        ) : (
            <LineGraphEmptyState color={color} isDashboard={!!dashboardItemId} />
        )
    ) : (
        <Loading />
    )
}
