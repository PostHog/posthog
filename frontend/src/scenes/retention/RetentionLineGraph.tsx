import React, { useState } from 'react'
import { dateOptions, retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { Loading } from '../../lib/utils'
import { router } from 'kea-router'
import { LineGraphEmptyState } from '../insights/EmptyStates'
import { Modal, Button } from 'antd'
import { PeopleTable } from 'scenes/users/PeopleTable'

interface RetentionLineGraphProps {
    dashboardItemId?: number | null
    color?: string
    inSharedMode?: boolean | null
}

export function RetentionLineGraph({
    dashboardItemId = null,
    color = 'white',
    inSharedMode = false,
}: RetentionLineGraphProps): JSX.Element {
    const logic = retentionTableLogic({ dashboardItemId: dashboardItemId })
    const { filters, retention, retentionLoading, people, peopleLoading } = useValues(logic)
    const { loadPeople } = useActions(logic)
    const [{ fromItem }] = useState(router.values.hashParams)
    const [modalVisible, setModalVisible] = useState(false)
    const [day, setDay] = useState(0)
    function closeModal(): void {
        setModalVisible(false)
    }

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
                isInProgress={!filters.selectedDate}
                dashboardItemId={dashboardItemId || fromItem}
                inSharedMode={inSharedMode}
                percentage={true}
                onClick={
                    dashboardItemId
                        ? null
                        : (point) => {
                              const { day } = point
                              loadPeople(day - 1) // start from 0
                              setDay(day - 1)
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
                {/* {people ? (
                <p>
                    Found {people.count === 99 ? '99+' : people.count} {people.count === 1 ? 'user' : 'users'}
                </p>
            ) : (
                <p>Loading users...</p>
            )} */}

                <PeopleTable loading={peopleLoading} people={people} />
                <div
                    style={{
                        margin: '1rem',
                        textAlign: 'center',
                    }}
                >
                    {/* {people?.next && (
                    <Button type="primary" onClick={loadMorePeople}>
                        {people?.loadingMore ? <Spin /> : 'Load more people'}
                    </Button>
                )} */}
                </div>
            </Modal>
        </>
    ) : (
        <LineGraphEmptyState color={color} />
    )
}
