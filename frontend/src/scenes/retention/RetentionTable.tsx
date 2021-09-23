import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Modal, Button, Spin } from 'antd'
import { percentage } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { retentionTableLogic } from './retentionTableLogic'
import { Tooltip } from 'lib/components/Tooltip'
import {
    RetentionTablePayload,
    RetentionTablePeoplePayload,
    RetentionTableAppearanceType,
} from 'scenes/retention/types'

import './RetentionTable.scss'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
dayjs.extend(utc)

import { ColumnsType } from 'antd/lib/table'
import clsx from 'clsx'

export function RetentionTable({ dashboardItemId = null }: { dashboardItemId?: number | null }): JSX.Element | null {
    const logic = retentionTableLogic({ dashboardItemId })
    const {
        results: _results,
        resultsLoading,
        peopleLoading,
        people: _people,
        loadingMore,
        filters: { period, date_to },
    } = useValues(logic)
    const results = _results as RetentionTablePayload[]
    const people = _people as RetentionTablePeoplePayload

    const { loadPeople, loadMorePeople } = useActions(logic)
    const [modalVisible, setModalVisible] = useState(false)
    const [selectedRow, selectRow] = useState(0)
    const [isLatestPeriod, setIsLatestPeriod] = useState(false)

    useEffect(() => {
        setIsLatestPeriod(periodIsLatest(date_to, period))
    }, [date_to, period])
    const columns: ColumnsType<Record<string, any>> = [
        {
            title: 'Date',
            key: 'date',
            render: (row) =>
                period === 'Hour' ? dayjs(row.date).format('MMM D, h A') : dayjs.utc(row.date).format('MMM D'),
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
        results[0].values.forEach((_: any, dayIndex: number) => {
            columns.push({
                title: results[dayIndex].label,
                key: `day::${dayIndex}`,
                render: (row) => {
                    if (dayIndex >= row.values.length) {
                        return ''
                    }
                    return renderPercentage(
                        row.values[dayIndex]['count'],
                        row.values[0]['count'],
                        isLatestPeriod && dayIndex === row.values.length - 1,
                        dayIndex === 0
                    )
                },
            })
        })
    }

    function dismissModal(): void {
        setModalVisible(false)
    }

    return (
        <>
            <Table
                data-attr="retention-table"
                size="small"
                className="retention-table"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowClassName={dashboardItemId ? '' : 'cursor-pointer'}
                dataSource={results}
                columns={columns}
                rowKey="date"
                loading={resultsLoading}
                onRow={(_, rowIndex: number | undefined) => ({
                    onClick: () => {
                        if (!dashboardItemId && rowIndex !== undefined) {
                            loadPeople(rowIndex)
                            setModalVisible(true)
                            selectRow(rowIndex)
                        }
                    },
                })}
            />
            {results && (
                <Modal
                    visible={modalVisible}
                    closable={true}
                    onCancel={dismissModal}
                    footer={<Button onClick={dismissModal}>Close</Button>}
                    style={{
                        top: 20,
                        minWidth: results[selectedRow]?.values[0]?.count === 0 ? '10%' : '90%',
                        fontSize: 16,
                    }}
                    title={results[selectedRow] ? dayjs(results[selectedRow].date).format('MMMM D, YYYY') : ''}
                >
                    {results && !peopleLoading ? (
                        <div>
                            {results[selectedRow]?.values[0]?.count === 0 ? (
                                <span>No persons during this period.</span>
                            ) : (
                                <div>
                                    <table className="table-bordered full-width">
                                        <tbody>
                                            <tr>
                                                <th />
                                                {results &&
                                                    results
                                                        .slice(0, results[selectedRow]?.values.length)
                                                        .map((data, index) => <th key={index}>{data.label}</th>)}
                                            </tr>
                                            <tr>
                                                <td>user_id</td>
                                                {results &&
                                                    results[selectedRow]?.values.map((data: any, index: number) => (
                                                        <td key={index}>
                                                            {data.count}&nbsp;{' '}
                                                            {data.count > 0 && (
                                                                <span>
                                                                    (
                                                                    {percentage(
                                                                        data.count /
                                                                            results[selectedRow]?.values[0]['count']
                                                                    )}
                                                                    )
                                                                </span>
                                                            )}
                                                        </td>
                                                    ))}
                                            </tr>
                                            {people.result &&
                                                people.result.map((personAppearances: RetentionTableAppearanceType) => (
                                                    <tr key={personAppearances.person.id}>
                                                        <td className="text-overflow" style={{ minWidth: 200 }}>
                                                            <Link
                                                                to={`/person/${encodeURIComponent(
                                                                    personAppearances.person.distinct_ids[0]
                                                                )}`}
                                                                data-attr="retention-person-link"
                                                            >
                                                                {personAppearances.person.name}
                                                            </Link>
                                                        </td>
                                                        {personAppearances.appearances.map(
                                                            (appearance: number, index: number) => {
                                                                return (
                                                                    <td
                                                                        key={index}
                                                                        className={
                                                                            appearance
                                                                                ? 'retention-success'
                                                                                : 'retention-dropped'
                                                                        }
                                                                    />
                                                                )
                                                            }
                                                        )}
                                                    </tr>
                                                ))}
                                        </tbody>
                                    </table>
                                    <div
                                        style={{
                                            margin: '1rem',
                                            textAlign: 'center',
                                        }}
                                    >
                                        {people.next ? (
                                            <Button
                                                type="primary"
                                                onClick={() => loadMorePeople()}
                                                loading={loadingMore}
                                            >
                                                Load more people
                                            </Button>
                                        ) : null}
                                    </div>
                                </div>
                            )}
                        </div>
                    ) : (
                        <Spin />
                    )}
                </Modal>
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

const periodIsLatest = (date_to: string, period: string): boolean => {
    if (!date_to) {
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
