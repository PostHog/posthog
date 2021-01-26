import React, { useState } from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { Loading } from '../../lib/utils'
import { router } from 'kea-router'
import { LineGraphEmptyState } from '../insights/EmptyStates'
import { Modal, Button, Spin } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { PersonType } from '~/types'

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
    filters: filtersParams = {},
}: RetentionLineGraphProps): JSX.Element | null {
    const logic = retentionTableLogic({ dashboardItemId: dashboardItemId, filters: filtersParams })
    const { filters, results, resultsLoading, people, peopleLoading } = useValues(logic)
    const { loadPeople, loadMorePeople } = useActions(logic)
    const [{ fromItem }] = useState(router.values.hashParams)
    const [modalVisible, setModalVisible] = useState(false)
    const [day, setDay] = useState(0)
    function closeModal(): void {
        setModalVisible(false)
    }
    const peopleData = people?.result as PersonType[]
    const peopleNext = people?.next
    if (results.length === 0) {
        return null
    }

    return resultsLoading ? (
        <Loading />
    ) : results && !resultsLoading ? (
        <>
            <LineGraph
                data-attr="trend-line-graph"
                type="line"
                color={color}
                datasets={results}
                labels={(results[0] && results[0].labels) || []}
                isInProgress={!filters.date_to}
                dashboardItemId={dashboardItemId || fromItem}
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
                    <p>Loading users...</p>
                )}

                <PersonsTable loading={peopleLoading} people={peopleData} />
                <div
                    style={{
                        margin: '1rem',
                        textAlign: 'center',
                    }}
                >
                    {peopleNext && (
                        <Button type="primary" onClick={loadMorePeople}>
                            {people?.loadingMore ? <Spin /> : 'Load more people'}
                        </Button>
                    )}
                </div>
            </Modal>
        </>
    ) : (
        <LineGraphEmptyState color={color} />
    )
}
