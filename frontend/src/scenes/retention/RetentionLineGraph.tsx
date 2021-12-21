import React, { useState } from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph/LineGraph'
import { useActions, useValues } from 'kea'
import { InsightEmptyState } from '../insights/EmptyStates'
import { Modal, Button } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { GraphType, PersonType, GraphDataset } from '~/types'
import { RetentionTablePayload, RetentionTablePeoplePayload, RetentionTrendPeoplePayload } from 'scenes/retention/types'
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
    const { results: _results, filters, trendSeries, people: _people, peopleLoading, loadingMore, aggregationTargetLabel } = useValues(logic)
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
                        : (point) => {
                              const { index } = point
                              console.log(point)
                              loadPeople(index) // start from 0
                              selectRow(index)
                              setModalVisible(true)
                          }
                }
            />
            {results && <RetentionModal
                results={results}
                actors={people}
                selectedRow={selectedRow}
                visible={modalVisible}
                dismissModal={() => setModalVisible(false)}
                actorsLoading={peopleLoading}
                loadMore={() => loadMorePeople()}
                loadingMore={loadingMore}
                aggregationTargetLabel={aggregationTargetLabel}
            />}
        </>
    ) : (
        <InsightEmptyState color={color} isDashboard={!!dashboardItemId} />
    )
}
