import React, { useState } from 'react'
import { dateOptions, retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { Loading } from '../../lib/utils'
import { router } from 'kea-router'
import { LineGraphEmptyState } from '../insights/EmptyStates'
import { Modal, Button, Spin } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'

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
}: RetentionLineGraphProps): JSX.Element {
    const logic = retentionTableLogic({ dashboardItemId: dashboardItemId, filters: filtersParams })
    const { filters, retention, retentionLoading, people, peopleLoading } = useValues(logic)
    const { loadPeople, loadMorePeople } = useActions(logic)
    const [{ fromItem }] = useState(router.values.hashParams)
    const [modalVisible, setModalVisible] = useState(false)
    const [day, setDay] = useState(0)
    function closeModal(): void {
        setModalVisible(false)
    }
    const peopleData = people?.result
    const peopleNext = people?.next

    return retentionLoading ? (
        <Loading />
    ) : retention && retention.data && !retentionLoading ? (
        <>
            <LineGraph
                pageKey={'trends-annotations'}
                data-attr="trend-line-graph"
                type="line"
                color={color}
                datasets={retention.data}
                labels={(retention.data[0] && retention.data[0].labels) || []}
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
                title={dateOptions[filters.period] + ' ' + day + ' people'}
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
