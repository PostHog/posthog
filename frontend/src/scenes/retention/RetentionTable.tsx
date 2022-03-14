import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { Table } from 'antd'
import { retentionTableLogic } from './retentionTableLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { RetentionTablePayload, RetentionTablePeoplePayload } from 'scenes/retention/types'
import { ColumnsType } from 'antd/lib/table'
import clsx from 'clsx'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import './RetentionTable.scss'

import { RetentionModal } from './RetentionModal'

export function RetentionTable({ inCardView = false }: { inCardView?: boolean }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = retentionTableLogic(insightProps)
    const {
        results: _results,
        resultsLoading,
        peopleLoading,
        people: _people,
        loadingMore,
        filters: { period, date_to, breakdowns },
        aggregationTargetLabel,
    } = useValues(logic)
    const results = _results as RetentionTablePayload[]
    const people = _people as RetentionTablePeoplePayload

    const { loadPeople, loadMorePeople } = useActions(logic)
    const [modalVisible, setModalVisible] = useState(false)
    const [selectedRow, selectRow] = useState(0)
    const [isLatestPeriod, setIsLatestPeriod] = useState(false)

    useEffect(() => {
        setIsLatestPeriod(periodIsLatest(date_to || null, period || null))
    }, [date_to, period])

    const columns: ColumnsType<Record<string, any>> = [
        {
            title: 'Cohort',
            key: 'cohort',
            render: (row: RetentionTablePayload) =>
                // If we have breakdowns, then use the returned label attribute
                // as the cohort name, otherwise we construct one ourselves
                // based on the returned date. It might be nice to just unify to
                // have label computed as such from the API.
                breakdowns?.length
                    ? row.label
                    : period === 'Hour'
                    ? dayjs(row.date).format('MMM D, h A')
                    : dayjs.utc(row.date).format('MMM D'),
            align: 'center',
        },
        {
            title: 'Cohort Size',
            key: 'users',
            render: (row) => row.values[0]['count'],
            align: 'center',
        },
    ]

    if (!resultsLoading && results) {
        if (results.length === 0) {
            return null
        }
        const maxIntervalsCount = Math.max(...results.map((result) => result.values.length))
        columns.push(
            ...Array.from(Array(maxIntervalsCount).keys()).map((index: number) => ({
                key: `period::${index}`,
                title: `${period} ${index}`,
                render: (row: RetentionTablePayload) => {
                    if (index >= row.values.length) {
                        return ''
                    }
                    return renderPercentage(
                        row.values[index]['count'],
                        row.values[0]['count'],
                        isLatestPeriod && index === row.values.length - 1,
                        index === 0
                    )
                },
            }))
        )
    }

    function dismissModal(): void {
        setModalVisible(false)
    }

    function loadMore(): void {
        loadMorePeople()
    }

    return (
        <>
            <Table
                data-attr="retention-table"
                size="small"
                className="retention-table"
                pagination={false}
                rowClassName={inCardView ? '' : 'cursor-pointer'}
                dataSource={results}
                columns={columns}
                rowKey="date"
                loading={resultsLoading}
                onRow={(_, rowIndex: number | undefined) => ({
                    onClick: () => {
                        if (!inCardView && rowIndex !== undefined) {
                            loadPeople(rowIndex)
                            setModalVisible(true)
                            selectRow(rowIndex)
                        }
                    },
                })}
            />
            {results && (
                <RetentionModal
                    results={results}
                    actors={people}
                    selectedRow={selectedRow}
                    visible={modalVisible}
                    dismissModal={dismissModal}
                    actorsLoading={peopleLoading}
                    loadMore={loadMore}
                    loadingMore={loadingMore}
                    aggregationTargetLabel={aggregationTargetLabel}
                />
            )}
        </>
    )
}

const renderPercentage = (value: number, total: number, latest = false, periodZero = false): JSX.Element => {
    const _percentage = total > 0 ? (100.0 * value) / total : 0
    const percentageBasisForColor = periodZero ? 100 : _percentage // So that Period 0 is always shown consistently
    const backgroundColor = `hsl(212, 63%, ${30 + (100 - percentageBasisForColor) * 0.65}%)`
    const color = percentageBasisForColor >= 65 ? 'hsl(0, 0%, 80%)' : undefined

    const numberCell = (
        <div style={{ backgroundColor, color }} className={clsx('percentage-cell', { 'period-in-progress': latest })}>
            {_percentage.toFixed(1)}%{latest && '*'}
        </div>
    )
    return latest ? <Tooltip title="Period in progress">{numberCell}</Tooltip> : numberCell
}

const periodIsLatest = (date_to: string | null, period: string | null): boolean => {
    if (!date_to || !period) {
        return true
    }

    const curr = dayjs(date_to)
    if (
        (period == 'Hour' && curr.isSame(dayjs(), 'hour')) ||
        (period == 'Day' && curr.isSame(dayjs(), 'day')) ||
        (period == 'Week' && curr.isSame(dayjs(), 'week')) ||
        (period == 'Month' && curr.isSame(dayjs(), 'month'))
    ) {
        return true
    } else {
        return false
    }
}
