import React, { useState, useEffect } from 'react'
import { LineGraph } from '../../insights/LineGraph/LineGraph'
import { getChartColors } from 'lib/colors'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { ActionFilter, FilterType, GraphType, InsightShortId } from '~/types'
import { personsModalLogic } from '../personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLabel } from 'lib/components/InsightLabel'
import { SeriesLetter } from 'lib/components/SeriesGlyph'

interface Props {
    dashboardItemId?: InsightShortId | null
    filters: Partial<FilterType>
    color?: string
    inSharedMode?: boolean | null
    cachedResults?: any
    showPersonsModal?: boolean
}

type DataSet = any

export function ActionsHorizontalBar({
    dashboardItemId = null,
    filters: filtersParam,
    color = 'white',
    showPersonsModal = true,
}: Props): JSX.Element | null {
    const [data, setData] = useState<DataSet[] | null>(null)
    const [total, setTotal] = useState(0)
    const { insightProps, insight, hiddenLegendKeys } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { loadPeople, loadPeopleFromUrl } = useActions(personsModalLogic)
    const { results, labelGroupType } = useValues(logic)

    function updateData(): void {
        const _data = [...results]
        _data.sort((a, b) => b.aggregated_value - a.aggregated_value)

        // If there are more series than colors, we reuse colors sequentially so all series are colored
        const rawColorList = getChartColors(color, results.length)
        const colorList = results.map((_, idx) => rawColorList[idx % rawColorList.length])

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
        if (results) {
            updateData()
        }
    }, [results, color])

    return data && total > 0 ? (
        <LineGraph
            data-attr="trend-bar-value-graph"
            type={GraphType.HorizontalBar}
            color={color}
            tooltip={{
                altTitle: function _renderAltTitle(tooltipData) {
                    return (
                        <>
                            <SeriesLetter
                                className="mr-025"
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
            insightId={insight.id}
            totalValue={total}
            hiddenLegendKeys={hiddenLegendKeys}
            interval={filtersParam?.interval}
            onClick={
                dashboardItemId || filtersParam.formula || !showPersonsModal
                    ? undefined
                    : (point) => {
                          const { value: pointValue, index, points, seriesId } = point

                          const dataset = points.referencePoint.dataset

                          const action = dataset.actions?.[point.index]
                          const label = dataset.labels?.[point.index]
                          const date_from = filtersParam?.date_from || ''
                          const date_to = filtersParam?.date_to || ''
                          const breakdown_value = dataset.breakdownValues?.[point.index]
                              ? dataset.breakdownValues[point.index]
                              : null
                          const params = {
                              action: action as ActionFilter,
                              label: label ?? '',
                              date_from,
                              date_to,
                              filters: filtersParam,
                              breakdown_value: breakdown_value ?? '',
                              pointValue,
                              seriesId,
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
