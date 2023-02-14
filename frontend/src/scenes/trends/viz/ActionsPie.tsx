import './ActionsPie.scss'
import { useState, useEffect } from 'react'
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
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import clsx from 'clsx'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

export function ActionsPie({ inSharedMode, inCardView, showPersonsModal = true }: ChartParams): JSX.Element | null {
    const [data, setData] = useState<GraphDataset[] | null>(null)
    const [total, setTotal] = useState(0)
    const { insightProps, insight } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, labelGroupType, hiddenLegendKeys, filters } = useValues(logic)

    function updateData(): void {
        const _data = [...indexedResults].sort((a, b) => b.aggregated_value - a.aggregated_value)
        const days = _data.length > 0 ? _data[0].days : []
        const colorList = _data.map(({ seriesIndex }) => getSeriesColor(seriesIndex))

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
                borderColor: colorList, // For colors to display in the tooltip
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
            <div
                className={clsx(
                    'ActionsPie w-full',
                    inCardView && 'flex flex-row h-full items-center',
                    isTrendsFilter(filters) && filters.show_legend && 'pr-4'
                )}
            >
                <div className={clsx('actions-pie-component', inCardView && 'grow')}>
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
                            filters={insight.filters}
                            onClick={
                                !showPersonsModal || (isTrendsFilter(insight.filters) && insight.filters?.formula)
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
                    <h3 className="text-7xl text-center font-bold m-0">
                        {formatAggregationAxisValue(insight.filters, total)}
                    </h3>
                </div>
                {inCardView && isTrendsFilter(filters) && filters.show_legend && <InsightLegend inCardView />}
            </div>
        ) : (
            <p className="text-center mt-16">We couldn't find any matching actions.</p>
        )
    ) : null
}
