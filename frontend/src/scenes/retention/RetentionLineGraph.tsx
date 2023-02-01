import { useState } from 'react'
import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionLogic } from './retentionLogic'
import { retentionPeopleLogic } from './retentionPeopleLogic'

import { GraphType, GraphDataset } from '~/types'
import { roundToDecimal } from 'lib/utils'
import { LineGraph } from '../insights/views/LineGraph/LineGraph'
import { InsightEmptyState } from '../insights/EmptyStates'
import { RetentionModal } from './RetentionModal'
import { retentionLineGraphLogic } from './retentionLineGraphLogic'

interface RetentionLineGraphProps {
    inSharedMode?: boolean
}

export function RetentionLineGraph({ inSharedMode = false }: RetentionLineGraphProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { results, filters, aggregationTargetLabel } = useValues(retentionLogic(insightProps))
    const { trendSeries, incompletenessOffsetFromEnd } = useValues(retentionLineGraphLogic(insightProps))
    const { people, peopleLoading, loadingMore } = useValues(retentionPeopleLogic(insightProps))
    const { loadPeople, loadMorePeople } = useActions(retentionPeopleLogic(insightProps))

    const [modalVisible, setModalVisible] = useState(false)
    const [selectedRow, setSelectedRow] = useState(0)

    if (trendSeries.length === 0) {
        return null
    }

    return trendSeries ? (
        <>
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
                    const datasetIndex = points.clickedPointNotLine
                        ? points.pointsIntersectingClick[0].dataset.index
                        : points.pointsIntersectingLine[0].dataset.index
                    if (datasetIndex) {
                        loadPeople(datasetIndex) // start from 0
                        setSelectedRow(datasetIndex)
                    }
                    setModalVisible(true)
                }}
                incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            />
            {results && (
                <RetentionModal
                    results={results}
                    actors={people}
                    selectedRow={selectedRow}
                    visible={modalVisible}
                    dismissModal={() => setModalVisible(false)}
                    actorsLoading={peopleLoading}
                    loadMore={() => loadMorePeople()}
                    loadingMore={loadingMore}
                    aggregationTargetLabel={aggregationTargetLabel}
                />
            )}
        </>
    ) : (
        <InsightEmptyState />
    )
}
