import './ActionsPie.scss'
import { useState, useEffect } from 'react'
import { getSeriesColor } from 'lib/colors'
import { useValues } from 'kea'
import { ChartParams, GraphType, GraphDataset, ChartDisplayType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { urlsForDatasets } from '../persons-modal/persons-modal-utils'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { trendsDataLogic } from '../trendsDataLogic'

export function ActionsPie({
    inSharedMode,
    inCardView,
    showPersonsModal = true,
    context,
}: ChartParams): JSX.Element | null {
    const [data, setData] = useState<GraphDataset[] | null>(null)
    const [total, setTotal] = useState(0)

    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const { insightProps, hiddenLegendKeys } = useValues(insightLogic)
    const {
        indexedResults,
        labelGroupType,
        trendsFilter,
        formula,
        showValueOnSeries,
        showLabelOnSeries,
        supportsPercentStackView,
        showPercentStackView,
        pieChartVizOptions,
    } = useValues(trendsDataLogic(insightProps))

    const renderingMetadata = context?.chartRenderingMetadata?.[ChartDisplayType.ActionsPie]

    const showAggregation = !pieChartVizOptions?.hideAggregation

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
                breakdownValues: _data.map((item) => {
                    return formatBreakdownLabel(
                        cohorts,
                        formatPropertyValueForDisplay,
                        item.breakdown_value,
                        item.filter?.breakdown,
                        item.filter?.breakdown_type,
                        false
                    )
                }),
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

    const onClick =
        renderingMetadata?.onSegmentClick ||
        (!showPersonsModal || formula
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
              })

    return data ? (
        data[0] && data[0].labels ? (
            <div className="ActionsPie">
                <div className="ActionsPie__component">
                    <div className="ActionsPie__chart">
                        <PieChart
                            data-attr="trend-pie-graph"
                            hiddenLegendKeys={hiddenLegendKeys}
                            type={GraphType.Pie}
                            datasets={data}
                            labels={data[0].labels}
                            labelGroupType={labelGroupType}
                            inSharedMode={!!inSharedMode}
                            showPersonsModal={showPersonsModal}
                            trendsFilter={trendsFilter}
                            formula={formula}
                            showValueOnSeries={showValueOnSeries}
                            showLabelOnSeries={showLabelOnSeries}
                            supportsPercentStackView={supportsPercentStackView}
                            showPercentStackView={showPercentStackView}
                            onClick={onClick}
                            disableHoverOffset={pieChartVizOptions?.disableHoverOffset}
                        />
                    </div>
                    {showAggregation && (
                        <h3 className="text-7xl text-center font-bold m-0">
                            {formatAggregationAxisValue(trendsFilter, total)}
                        </h3>
                    )}
                </div>
                {inCardView && trendsFilter?.show_legend && <InsightLegend inCardView />}
            </div>
        ) : (
            <p className="text-center mt-16">We couldn't find any matching actions.</p>
        )
    ) : null
}
