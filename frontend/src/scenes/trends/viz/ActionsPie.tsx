import './ActionsPie.scss'

import React, { useState, useEffect } from 'react'
import { maybeAddCommasToInteger } from 'lib/utils'
import { LineGraph } from '../../insights/LineGraph'
import { getChartColors } from 'lib/colors'
import { useValues, useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ChartParams, TrendResultWithAggregate } from '~/types'
import { personsModalLogic } from '../personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function ActionsPie({
    dashboardItemId,
    filters: filtersParam,
    color = 'white',
    inSharedMode,
    showPersonsModal = true,
}: ChartParams): JSX.Element | null {
    const [data, setData] = useState<Record<string, any>[] | null>(null)
    const [total, setTotal] = useState(0)
    const { insightProps } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { loadPeople, loadPeopleFromUrl } = useActions(personsModalLogic)
    const { results } = useValues(logic)

    function updateData(): void {
        const _data = [...results] as TrendResultWithAggregate[]
        _data.sort((a, b) => b.aggregated_value - a.aggregated_value)
        const days = results.length > 0 ? results[0].days : []

        const colorList = getChartColors(color, results.length)

        setData([
            {
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                actions: _data.map((item) => item.action),
                breakdownValues: _data.map((item) => item.breakdown_value),
                persons: _data.map((item) => item.persons),
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

    return data ? (
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
                        onClick={
                            dashboardItemId || filtersParam.formula || !showPersonsModal
                                ? null
                                : (point) => {
                                      const { dataset, index } = point
                                      const action = dataset.actions[point.index]
                                      const label = dataset.labels[point.index]
                                      const date_from = filtersParam.date_from || ''
                                      const date_to = filtersParam.date_to || ''
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
                </div>
                <h1>
                    <span className="label">Total: </span>
                    {maybeAddCommasToInteger(total)}
                </h1>
            </div>
        ) : (
            <p style={{ textAlign: 'center', marginTop: '4rem' }}>We couldn't find any matching actions.</p>
        )
    ) : null
}
