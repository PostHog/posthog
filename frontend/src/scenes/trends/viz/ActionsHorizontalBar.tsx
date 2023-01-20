import { useState, useEffect } from 'react'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { getSeriesColor } from 'lib/colors'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { ChartParams, GraphType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { urlsForDatasets } from '../persons-modal/persons-modal-utils'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

type DataSet = any

export function ActionsHorizontalBar({ inCardView, showPersonsModal = true }: ChartParams): JSX.Element | null {
    const [data, setData] = useState<DataSet[] | null>(null)
    const [total, setTotal] = useState(0)
    const { insightProps, insight, hiddenLegendKeys } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { indexedResults, labelGroupType } = useValues(logic)

    function updateData(): void {
        const _data = [...indexedResults]
        const colorList = indexedResults.map((_, idx) => getSeriesColor(idx))

        setData([
            {
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                actions: _data.map((item) => item.action),
                personsValues: _data.map((item) => item.persons),
                breakdownValues: _data.map((item) => item.breakdown_value),
                compareLabels: _data.map((item) => item.compare_label),
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
        if (indexedResults) {
            updateData()
        }
    }, [indexedResults])

    return data && total > 0 ? (
        <LineGraph
            data-attr="trend-bar-value-graph"
            type={GraphType.HorizontalBar}
            tooltip={{
                altTitle: function _renderAltTitle(tooltipData) {
                    return (
                        <>
                            <SeriesLetter
                                className="mr-1"
                                hasBreakdown={false}
                                seriesIndex={tooltipData?.[0]?.action?.order ?? 0}
                            />
                            <InsightLabel
                                className="series-column-header"
                                action={tooltipData?.[0]?.action}
                                fallbackName="Series"
                                hideBreakdown
                                hideCompare
                                hideIcon
                                allowWrap
                            />
                        </>
                    )
                },
            }}
            labelGroupType={labelGroupType}
            datasets={data}
            labels={data[0].labels}
            hiddenLegendKeys={hiddenLegendKeys}
            showPersonsModal={showPersonsModal}
            filters={insight.filters}
            inCardView={inCardView}
            onClick={
                !showPersonsModal || (isTrendsFilter(insight.filters) && insight.filters.formula)
                    ? undefined
                    : (point) => {
                          const { index, points, crossDataset } = point

                          const dataset = points.referencePoint.dataset
                          const label = dataset.labels?.[point.index]
                          const urls = urlsForDatasets(crossDataset, index)
                          const selectedUrl = urls[index]?.value

                          if (selectedUrl) {
                              openPersonsModal({
                                  urlsIndex: index,
                                  urls,
                                  title: <PropertyKeyInfo value={label || ''} disablePopover />,
                              })
                          }
                      }
            }
        />
    ) : (
        <InsightEmptyState />
    )
}
