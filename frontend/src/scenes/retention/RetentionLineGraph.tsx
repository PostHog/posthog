import React, { useState } from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph/LineGraph'
import { useActions, useValues } from 'kea'
import { InsightEmptyState } from '../insights/EmptyStates'
import { GraphType, GraphDataset } from '~/types'
import { RetentionTablePayload, RetentionTablePeoplePayload } from 'scenes/retention/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import './RetentionLineGraph.scss'
import { RetentionModal } from './RetentionModal'

interface RetentionLineGraphProps {
    dashboardItemId?: number | null
    color?: string
    inSharedMode?: boolean | null
    filters?: Record<string, unknown>
}

export function RetentionLineGraph({
    dashboardItemId = null,
    color = 'white',
    inSharedMode = false,
}: RetentionLineGraphProps): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const logic = retentionTableLogic(insightProps)
    const {
        results: _results,
        filters,
        trendSeries,
        people: _people,
        peopleLoading,
        loadingMore,
        aggregationTargetLabel,
    } = useValues(logic)
    const results = _results as RetentionTablePayload[]
    const people = _people as RetentionTablePeoplePayload

    const { loadPeople, loadMorePeople } = useActions(logic)
    const [modalVisible, setModalVisible] = useState(false)
    const [selectedRow, selectRow] = useState(0)

    if (trendSeries.length === 0) {
        return null
    }
    return trendSeries ? (
        <>
            <LineGraph
                data-attr="trend-line-graph"
                type={GraphType.Line}
                color={color}
                datasets={trendSeries as GraphDataset[]}
                labels={(trendSeries[0] && trendSeries[0].labels) || []}
                isInProgress={!filters.date_to}
                insightId={insight.id}
                inSharedMode={!!inSharedMode}
                percentage={true}
                onClick={
                    dashboardItemId
                        ? undefined
                        : (payload) => {
                              const { points } = payload
                              const datasetIndex = points.clickedPointNotLine
                                  ? points.pointsIntersectingClick[0].dataset.index
                                  : points.pointsIntersectingLine[0].dataset.index
                              if (datasetIndex) {
                                  loadPeople(datasetIndex) // start from 0
                                  selectRow(datasetIndex)
                              }
                              setModalVisible(true)
                          }
                }
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
        <InsightEmptyState color={color} isDashboard={!!dashboardItemId} />
    )
}
