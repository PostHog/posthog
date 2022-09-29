import './ActionsPie.scss'
import React, { useState, useEffect } from 'react'
import { getSeriesColor } from 'lib/colors'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ChartParams, GraphType, GraphDataset } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { urlsForDatasets } from '../persons-modal/persons-modal-utils'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'

export function ActionsPie({ inSharedMode, showPersonsModal = true }: ChartParams): JSX.Element | null {
    const [data, setData] = useState<GraphDataset[] | null>(null)
    const [total, setTotal] = useState(0)
    const { insightProps, insight } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
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
                    <PieChart
                        data-attr="trend-pie-graph"
                        hiddenLegendKeys={hiddenLegendKeys}
                        type={GraphType.Pie}
                        datasets={data}
                        labels={data[0].labels}
                        labelGroupType={labelGroupType}
                        inSharedMode={!!inSharedMode}
                        showPersonsModal={showPersonsModal}
                        aggregationAxisFormat={insight.filters?.aggregation_axis_format}
                        onClick={
                            !showPersonsModal || insight.filters?.formula
                                ? undefined
                                : (payload) => {
                                      const { points, index, crossDataset } = payload
                                      const dataset = points.referencePoint.dataset
                                      const label = dataset.labels?.[index]

                                      const urls = urlsForDatasets(crossDataset, index)
                                      const selectedUrl = urls[index]?.value

                                      if (selectedUrl) {
                                          openPersonsModal({
                                              urls,
                                              urlsIndex: index,
                                              title: <PropertyKeyInfo value={label || ''} disablePopover />,
                                          })
                                      }
                                  }
                        }
                    />
                </div>
                <h1 className="text-7xl text-center">
                    {formatAggregationAxisValue(insight.filters?.aggregation_axis_format, total)}
                </h1>
            </div>
        ) : (
            <p className="text-center mt-16">We couldn't find any matching actions.</p>
        )
    ) : null
}
