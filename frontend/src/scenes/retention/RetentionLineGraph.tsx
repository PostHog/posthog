import { useActions, useValues } from 'kea'
import { roundToDecimal } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { TrendsFilter } from '~/queries/schema'
import { GraphDataset, GraphType } from '~/types'

import { InsightEmptyState } from '../insights/EmptyStates'
import { LineGraph } from '../insights/views/LineGraph/LineGraph'
import { retentionLineGraphLogic } from './retentionLineGraphLogic'
import { retentionModalLogic } from './retentionModalLogic'

interface RetentionLineGraphProps {
    inSharedMode?: boolean
}

export function RetentionLineGraph({ inSharedMode = false }: RetentionLineGraphProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { trendSeries, incompletenessOffsetFromEnd, aggregationGroupTypeIndex } = useValues(
        retentionLineGraphLogic(insightProps)
    )
    const { openModal } = useActions(retentionModalLogic(insightProps))

    if (trendSeries.length === 0) {
        return null
    }

    return trendSeries ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={GraphType.Line}
            datasets={trendSeries as GraphDataset[]}
            labels={(trendSeries[0] && trendSeries[0].labels) || []}
            isInProgress={incompletenessOffsetFromEnd < 0}
            inSharedMode={!!inSharedMode}
            showPersonsModal={false}
            labelGroupType={aggregationGroupTypeIndex}
            trendsFilter={{ aggregationAxisFormat: 'percentage' } as TrendsFilter}
            tooltip={{
                rowCutoff: 11, // 11 time units is hardcoded into retention insights
                renderSeries: function _renderCohortPrefix(value) {
                    return (
                        <>
                            {value}
                            <span className="ml-1">Cohort</span>
                        </>
                    )
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
