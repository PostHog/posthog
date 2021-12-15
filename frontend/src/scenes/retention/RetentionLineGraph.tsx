import React, { useState } from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { InsightEmptyState } from '../insights/EmptyStates'
import { Modal, Button } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { PersonType } from '~/types'
import { RetentionTrendPeoplePayload } from 'scenes/retention/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import './RetentionLineGraph.scss'

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
    const { insightProps } = useValues(insightLogic)
    const logic = retentionTableLogic(insightProps)
    const { filters, trendSeries, people: _people, peopleLoading, loadingMore } = useValues(logic)
    const people = _people as RetentionTrendPeoplePayload

    const { loadPeople, loadMorePeople } = useActions(logic)
    const [modalVisible, setModalVisible] = useState(false)
    const [day, setDay] = useState(0)
    function closeModal(): void {
        setModalVisible(false)
    }
    const peopleData = people?.result as PersonType[]
    const peopleNext = people?.next
    if (trendSeries.length === 0) {
        return null
    }

    return trendSeries ? (
        <>
            <LineGraph
                data-attr="trend-line-graph"
                type="line"
                color={color}
                datasets={trendSeries}
                labels={(trendSeries[0] && trendSeries[0].labels) || []}
                isInProgress={!filters.date_to}
                dashboardItemId={dashboardItemId}
                inSharedMode={inSharedMode}
                percentage={true}
                onClick={
                    dashboardItemId
                        ? null
                        : (point) => {
                              const { index } = point
                              loadPeople(index) // start from 0
                              setDay(index)
                              setModalVisible(true)
                          }
                }
            />
            <Modal
                title={filters.period + ' ' + day + ' people'}
                visible={modalVisible}
                onOk={closeModal}
                onCancel={closeModal}
                footer={<Button onClick={closeModal}>Close</Button>}
                width={700}
            >
                {peopleData ? (
                    <p>
                        Found {peopleData.length === 99 ? '99+' : peopleData.length}{' '}
                        {peopleData.length === 1 ? 'user' : 'users'}
                    </p>
                ) : (
                    <p>Loading persons…</p>
                )}
                <PersonsTable loading={peopleLoading} people={peopleData} compact />
                <div
                    style={{
                        margin: '1rem',
                        textAlign: 'center',
                    }}
                >
                    {peopleNext && (
                        <Button type="primary" onClick={loadMorePeople} loading={loadingMore}>
                            Load more people
                        </Button>
                    )}
                </div>
            </Modal>
        </>
    ) : (
        <InsightEmptyState color={color} isDashboard={!!dashboardItemId} />
    )
}
