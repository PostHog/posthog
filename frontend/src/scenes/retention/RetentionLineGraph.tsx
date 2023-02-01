import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionLogic } from './retentionLogic'
import { retentionLineGraphLogic } from './retentionLineGraphLogic'
import { retentionModalLogic } from './retentionModalLogic'

import { GraphType, GraphDataset } from '~/types'
import { roundToDecimal } from 'lib/utils'
import { LineGraph } from '../insights/views/LineGraph/LineGraph'
import { InsightEmptyState } from '../insights/EmptyStates'

interface RetentionLineGraphProps {
    inSharedMode?: boolean
}

export function RetentionLineGraph({ inSharedMode = false }: RetentionLineGraphProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { filters } = useValues(retentionLogic(insightProps))
    const { trendSeries, incompletenessOffsetFromEnd } = useValues(retentionLineGraphLogic(insightProps))
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
            labelGroupType={filters.aggregation_group_type_index ?? 'people'}
            filters={{ aggregation_axis_format: 'percentage' }}
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

                openModal(rowIndex)
            }}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
        />
    ) : (
        <InsightEmptyState />
    )
}
