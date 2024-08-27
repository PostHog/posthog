import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import { ChartParams, GraphType } from '~/types'

import { InsightEmptyState } from '../../insights/EmptyStates'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { trendsDataLogic } from '../trendsDataLogic'

type DataSet = any

export function ActionsHorizontalBar({ showPersonsModal = true }: ChartParams): JSX.Element | null {
    const [data, setData] = useState<DataSet[] | null>(null)
    const [total, setTotal] = useState(0)

    const { insightProps } = useValues(insightLogic)
    const {
        indexedResults,
        labelGroupType,
        trendsFilter,
        formula,
        showValuesOnSeries,
        isDataWarehouseSeries,
        querySource,
        hiddenLegendIndexes,
    } = useValues(trendsDataLogic(insightProps))

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
                breakdownLabels: _data.map((item) => item.label),
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
            hiddenLegendIndexes={hiddenLegendIndexes}
            showPersonsModal={showPersonsModal}
            trendsFilter={trendsFilter}
            formula={formula}
            showValuesOnSeries={showValuesOnSeries}
            onClick={
                !showPersonsModal || trendsFilter?.formula || isDataWarehouseSeries
                    ? undefined
                    : (point) => {
                          const { index, points } = point

                          const dataset = points.referencePoint.dataset
                          const label = dataset.labels?.[point.index]

                          openPersonsModal({
                              title: label || '',
                              query: datasetToActorsQuery({ dataset, query: querySource!, index }),
                              additionalSelect: {
                                  value_at_data_point: 'event_count',
                                  matched_recordings: 'matched_recordings',
                              },
                              orderBy: ['event_count DESC, actor_id DESC'],
                          })
                      }
            }
        />
    ) : (
        <InsightEmptyState />
    )
}
