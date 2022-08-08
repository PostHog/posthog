import './ActionsPie.scss'
import React, { useState, useEffect } from 'react'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { getSeriesColor } from 'lib/colors'
import { useValues, useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ChartParams, GraphType, GraphDataset, ActionFilter } from '~/types'
import { personsModalLogic } from '../personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'

export function ActionsPie({ inSharedMode, showPersonsModal = true }: ChartParams): JSX.Element | null {
    const [data, setData] = useState<GraphDataset[] | null>(null)
    const [total, setTotal] = useState(0)
    const { insightProps, insight } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { loadPeople, loadPeopleFromUrl } = useActions(personsModalLogic)
    const { indexedResults, labelGroupType, hiddenLegendKeys } = useValues(logic)

    function updateData(): void {
        const _data = [...indexedResults].sort((a, b) => b.aggregated_value - a.aggregated_value)
        const days = _data.length > 0 ? _data[0].days : []
        const colorList = _data.map(({ id }) => getSeriesColor(id))

        setData([
            {
                id: 0,
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                actions: _data.map((item) => item.action),
                breakdownValues: _data.map((item) => item.breakdown_value),
                personsValues: _data.map((item) => item.persons),
                days,
                backgroundColor: colorList,
                hoverBackgroundColor: colorList,
                hoverBorderColor: colorList,
                borderColor: colorList,
                hoverBorderWidth: 10,
                borderWidth: 1,
            },
        ])
        setTotal(_data.reduce((prev, item, i) => prev + (!hiddenLegendKeys?.[i] ? item.aggregated_value : 0), 0))
    }

    useEffect(() => {
        if (indexedResults) {
            updateData()
        }
    }, [indexedResults, hiddenLegendKeys])

    return data ? (
        data[0] && data[0].labels ? (
            <div className="actions-pie-component">
                <div className="pie-chart">
                    <LineGraph
                        data-attr="trend-pie-graph"
                        hiddenLegendKeys={hiddenLegendKeys}
                        type={GraphType.Pie}
                        datasets={data}
                        labels={data[0].labels}
                        labelGroupType={labelGroupType}
                        inSharedMode={!!inSharedMode}
                        insightNumericId={insight.id}
                        showPersonsModal={showPersonsModal}
                        aggregationAxisFormat={insight.filters?.aggregation_axis_format}
                        onClick={
                            !showPersonsModal || insight.filters?.formula
                                ? undefined
                                : (payload) => {
                                      const { points, index, seriesId } = payload
                                      const dataset = points.referencePoint.dataset
                                      const action = dataset.actions?.[index]
                                      const label = dataset.labels?.[index]
                                      const date_from = insight.filters?.date_from || ''
                                      const date_to = insight.filters?.date_to || ''
                                      const breakdown_value = dataset.breakdownValues?.[index]
                                          ? dataset.breakdownValues[index]
                                          : null
                                      const params = {
                                          action: action as ActionFilter,
                                          label: label ?? '',
                                          date_from,
                                          date_to,
                                          filters: insight.filters ?? {},
                                          seriesId,
                                          breakdown_value: breakdown_value ?? '',
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
                    {formatAggregationAxisValue(insight.filters?.aggregation_axis_format, total)}
                </h1>
            </div>
        ) : (
            <p className="text-center mt-16">We couldn't find any matching actions.</p>
        )
    ) : null
}
