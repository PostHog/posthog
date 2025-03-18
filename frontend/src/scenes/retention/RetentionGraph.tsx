import { useActions, useValues } from 'kea'
import { roundToDecimal } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { TrendsFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType, GraphDataset, GraphType } from '~/types'

import { InsightEmptyState } from '../insights/EmptyStates'
import { LineGraph } from '../insights/views/LineGraph/LineGraph'
import { retentionGraphLogic } from './retentionGraphLogic'
import { retentionModalLogic } from './retentionModalLogic'

interface RetentionGraphProps {
    inSharedMode?: boolean
    chartType?: 'line' | 'bar'
}

function displayTypeToGraphType(displayType: ChartDisplayType): GraphType {
    switch (displayType) {
        case ChartDisplayType.ActionsBar:
            return GraphType.Bar
        default:
            return GraphType.Line
    }
}

export function RetentionGraph({ inSharedMode = false }: RetentionGraphProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter, trendSeries, incompletenessOffsetFromEnd, aggregationGroupTypeIndex } = useValues(
        retentionGraphLogic(insightProps)
    )
    const { openModal } = useActions(retentionModalLogic(insightProps))

    if (trendSeries.length === 0) {
        return null
    }

    return trendSeries ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={displayTypeToGraphType(retentionFilter?.display || ChartDisplayType.ActionsLineGraph)}
            datasets={trendSeries as GraphDataset[]}
            labels={(trendSeries[0] && trendSeries[0].labels) || []}
            isInProgress={incompletenessOffsetFromEnd < 0}
            inSharedMode={!!inSharedMode}
            showPersonsModal={false}
            labelGroupType={aggregationGroupTypeIndex}
            // in retention graph, we want the bars side by side so it's easier
            // to see the retention trend change for each cohort
            isStacked={retentionFilter?.display !== ChartDisplayType.ActionsBar}
            trendsFilter={{ aggregationAxisFormat: 'percentage' } as TrendsFilter}
            tooltip={{
                rowCutoff: 11, // 11 time units is hardcoded into retention insights
                renderSeries: function _renderCohortPrefix(value) {
                    return <>Cohort {value}</>
                },
                showHeader: false,
                renderCount: (count) => {
                    return `${roundToDecimal(count)}%`
                },
            }}
            onClick={(payload) => {
                const { points } = payload
                const rowIndex = points.clickedPointNotLine
                    ? points.pointsIntersectingClick[0].dataset.index
                    : points.pointsIntersectingLine[0].dataset.index

                // we should always have a rowIndex, but adding a guard nonetheless
                if (rowIndex !== undefined) {
                    openModal(rowIndex)
                }
            }}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
        />
    ) : (
        <InsightEmptyState />
    )
}
