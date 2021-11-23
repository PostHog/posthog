import React, { useState, useEffect } from 'react'
import { LineGraph } from '../../insights/LineGraph'
import { getChartColors } from 'lib/colors'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { FilterType, TrendResultWithAggregate } from '~/types'
import { personsModalLogic } from '../personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

interface Props {
    dashboardItemId?: number | null
    filters: Partial<FilterType>
    color?: string
    inSharedMode?: boolean | null
    cachedResults?: any
    showPersonsModal?: boolean
}

type DataSet = any

export function ActionsBarValueGraph({
    dashboardItemId = null,
    filters: filtersParam,
    color = 'white',
    showPersonsModal = true,
}: Props): JSX.Element | null {
    const [data, setData] = useState<DataSet[] | null>(null)
    const [total, setTotal] = useState(0)
    const { insightProps } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { loadPeople, loadPeopleFromUrl } = useActions(personsModalLogic)
    const { results } = useValues(logic)

    function updateData(): void {
        const _data = [...results] as TrendResultWithAggregate[]
        _data.sort((a, b) => b.aggregated_value - a.aggregated_value)

        // If there are more series than colors, we reuse colors sequentially so all series are colored
        const rawColorList = getChartColors(color)
        const colorList = results.map((_, idx) => rawColorList[idx % rawColorList.length])

        const days = results.length > 0 ? results[0].days : []
        setData([
            {
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                actions: _data.map((item) => item.action),
                persons: _data.map((item) => item.persons),
                days,
                breakdownValues: _data.map((item) => item.breakdown_value),
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

    return data && total > 0 ? (
        <LineGraph
            data-attr="trend-bar-value-graph"
            type="horizontalBar"
            color={color}
            datasets={data}
            labels={data[0].labels}
            dashboardItemId={dashboardItemId}
            totalValue={total}
            interval={filtersParam?.interval}
            onClick={
                dashboardItemId || filtersParam.formula || !showPersonsModal
                    ? null
                    : (point) => {
                          const { dataset, value: pointValue, index } = point
                          const action = dataset.actions[point.index]
                          const label = dataset.labels[point.index]
                          const date_from = filtersParam?.date_from || ''
                          const date_to = filtersParam?.date_to || ''
                          const breakdown_value = dataset.breakdownValues[point.index]
                              ? dataset.breakdownValues[point.index]
                              : null
                          const params = {
                              action,
                              label,
                              date_from,
                              date_to,
                              filters: filtersParam,
                              breakdown_value,
                              pointValue,
                          }
                          if (dataset.persons_urls?.[index].url) {
                              loadPeopleFromUrl({
                                  ...params,
                                  url: dataset.persons_urls?.[index].url,
                              })
                          } else {
                              loadPeople(params)
                          }
                      }
            }
        />
    ) : (
        <InsightEmptyState color={color} isDashboard={!!dashboardItemId} />
    )
}
