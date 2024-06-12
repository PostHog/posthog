import './ActionsPie.scss'

import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { InsightLegend } from 'lib/components/InsightLegend/InsightLegend'
import { useEffect, useState } from 'react'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { PieChart } from 'scenes/insights/views/LineGraph/PieChart'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartDisplayType, ChartParams, GraphDataset, GraphType } from '~/types'

import { openPersonsModal } from '../persons-modal/PersonsModal'
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
        showValuesOnSeries,
        showLabelOnSeries,
        supportsPercentStackView,
        showPercentStackView,
        pieChartVizOptions,
        isDataWarehouseSeries,
        querySource,
    } = useValues(trendsDataLogic(insightProps))

    const renderingMetadata = context?.chartRenderingMetadata?.[ChartDisplayType.ActionsPie]

    const showAggregation = !pieChartVizOptions?.hideAggregation

    function updateData(): void {
        const days = indexedResults.length > 0 ? indexedResults[0].days : []
        const colorList = indexedResults.map(({ seriesIndex }) => getSeriesColor(seriesIndex))

        setData([
            {
                id: 0,
                labels: indexedResults.map((item) => item.label),
                data: indexedResults.map((item) => item.aggregated_value),
                actions: indexedResults.map((item) => item.action),
                breakdownValues: indexedResults.map((item) => item.breakdown_value),
                breakdownLabels: indexedResults.map((item) => {
                    return formatBreakdownLabel(
                        cohorts,
                        formatPropertyValueForDisplay,
                        item.breakdown_value,
                        item.filter?.breakdown,
                        item.filter?.breakdown_type,
                        false
                    )
                }),
                compareLabels: indexedResults.map((item) => item.compare_label),
                personsValues: indexedResults.map((item) => item.persons),
                days,
                backgroundColor: colorList,
                borderColor: colorList, // For colors to display in the tooltip
            },
        ])
        setTotal(
            indexedResults.reduce((prev, item, i) => prev + (!hiddenLegendKeys?.[i] ? item.aggregated_value : 0), 0)
        )
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
                  const { points, index } = payload
                  const dataset = points.referencePoint.dataset
                  const label = dataset.labels?.[index]

                  openPersonsModal({
                      title: label || '',
                      query: datasetToActorsQuery({ dataset, query: querySource!, index }),
                      additionalSelect: {
                          value_at_data_point: 'event_count',
                          matched_recordings: 'matched_recordings',
                      },
                      orderBy: ['event_count DESC, actor_id DESC'],
                  })
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
                            showValuesOnSeries={showValuesOnSeries}
                            showLabelOnSeries={showLabelOnSeries}
                            supportsPercentStackView={supportsPercentStackView}
                            showPercentStackView={showPercentStackView}
                            onClick={isDataWarehouseSeries ? undefined : onClick}
                            disableHoverOffset={pieChartVizOptions?.disableHoverOffset}
                        />
                    </div>
                    {showAggregation && (
                        <div className="text-7xl text-center font-bold m-0">
                            {formatAggregationAxisValue(trendsFilter, total)}
                        </div>
                    )}
                </div>
                {inCardView && trendsFilter?.showLegend && <InsightLegend inCardView />}
            </div>
        ) : (
            <p className="text-center mt-16">We couldn't find any matching actions.</p>
        )
    ) : null
}
