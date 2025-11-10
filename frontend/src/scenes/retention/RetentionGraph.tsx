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
    const {
        hasValidBreakdown,
        retentionFilter,
        filteredTrendSeries,
        incompletenessOffsetFromEnd,
        aggregationGroupTypeIndex,
        shouldShowMeanPerBreakdown,
        showTrendLines,
    } = useValues(retentionGraphLogic(insightProps))
    const { openModal } = useActions(retentionModalLogic(insightProps))

    const selectedInterval = retentionFilter?.selectedInterval ?? null

    if (filteredTrendSeries.length === 0 && hasValidBreakdown) {
        return (
            <p className="w-full m-0 text-center text-sm text-gray-500">
                Select a breakdown to see the retention graph
            </p>
        )
    }

    return filteredTrendSeries ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={displayTypeToGraphType(retentionFilter?.display || ChartDisplayType.ActionsLineGraph)}
            datasets={filteredTrendSeries as GraphDataset[]}
            labels={(filteredTrendSeries[0] && filteredTrendSeries[0].labels) || []}
            isInProgress={incompletenessOffsetFromEnd < 0}
            inSharedMode={!!inSharedMode}
            showPersonsModal={false}
            labelGroupType={aggregationGroupTypeIndex}
            // in retention graph, we want the bars side by side so it's easier
            // to see the retention trend change for each cohort
            isStacked={retentionFilter?.display !== ChartDisplayType.ActionsBar}
            trendsFilter={{ aggregationAxisFormat: 'percentage' } as TrendsFilter}
            tooltip={{
                altTitle: selectedInterval !== null ? `${retentionFilter?.period} ${selectedInterval}` : undefined,
                renderSeries: function _renderCohortPrefix(value) {
                    // If we're showing an interval view, show "Cohort: <date>"
                    if (selectedInterval !== null) {
                        return <>Cohort {value}</>
                    }
                    // If we're showing mean values per breakdown, show the breakdown value directly
                    if (shouldShowMeanPerBreakdown) {
                        return <>{value}</>
                    }
                    // Otherwise prefix with "Cohort" for normal cohort view
                    return <>Cohort {value}</>
                },
                showHeader: selectedInterval !== null,
                renderCount: (count) => {
                    return `${roundToDecimal(count)}%`
                },
            }}
            onClick={(payload) => {
                // Only open the modal if we're not showing mean values (which don't map to specific cohorts)
                if (shouldShowMeanPerBreakdown) {
                    return
                }

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
            showTrendLines={showTrendLines}
        />
    ) : (
        <InsightEmptyState />
    )
}
