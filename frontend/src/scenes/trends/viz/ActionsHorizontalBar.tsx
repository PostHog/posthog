import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartParams, GraphType } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { urlsForDatasets } from '../persons-modal/persons-modal-utils'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'

type DataSet = any

export function ActionsHorizontalBar({ showPersonsModal = true }: ChartParams): JSX.Element | null {
    const [data, setData] = useState<DataSet[] | null>(null)
    const [total, setTotal] = useState(0)

    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const { insightProps, hiddenLegendKeys } = useValues(insightLogic)
    const { indexedResults, labelGroupType, trendsFilter, formula, showValueOnSeries } = useValues(
        trendsDataLogic(insightProps)
    )

    function updateData(): void {
        const _data = [...indexedResults]
        const colorList = indexedResults.map((_, idx) => getSeriesColor(idx))

        setData([
            {
                labels: _data.map((item) => item.label),
                data: _data.map((item) => item.aggregated_value),
                actions: _data.map((item) => item.action),
                personsValues: _data.map((item) => item.persons),
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
                showHeader: false,
            }}
            labelGroupType={labelGroupType}
            datasets={data}
            labels={data[0].labels}
            hiddenLegendKeys={hiddenLegendKeys}
            showPersonsModal={showPersonsModal}
            trendsFilter={trendsFilter}
            formula={formula}
            showValueOnSeries={showValueOnSeries}
            onClick={
                !showPersonsModal || trendsFilter?.formula
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
