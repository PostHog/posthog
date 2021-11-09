import React, { useState } from 'react'
import dayjs from 'dayjs'
import { retentionTableLogic } from './retentionTableLogic'
import { LineGraph } from '../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { LineGraphEmptyState } from '../insights/EmptyStates'
import { Modal, Button } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { PersonType } from '~/types'
import { RetentionTrendPayload, RetentionTrendPeoplePayload } from 'scenes/retention/types'
import { router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'

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
    const { filters, results: _results, people: _people, peopleLoading, loadingMore } = useValues(logic)
    const results = _results as RetentionTrendPayload[]
    const people = _people as RetentionTrendPeoplePayload

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

    return results ? (
        <>
            <LineGraph
                data-attr="trend-line-graph"
                type="line"
                color={color}
                datasets={results}
                labels={(results[0] && results[0].labels) || []}
                isInProgress={!filters.date_to}
                dashboardItemId={
                    dashboardItemId || fromItem /* used only for annotations, not to init any other logic */
                }
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
                <PersonsTable
                    loading={peopleLoading}
                    people={peopleData}
                    date={filters.date_to ? dayjs(filters.date_to).format('YYYY-MM-DD') : undefined}
                    backTo="Insights"
                />
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
        <LineGraphEmptyState color={color} isDashboard={!!dashboardItemId} />
    )
}
