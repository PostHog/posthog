import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Modal, Button, Spin, Tooltip } from 'antd'
import { percentage } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { retentionTableLogic } from './retentionTableLogic'
import './RetentionTable.scss'
import moment from 'moment'
import { ColumnsType } from 'antd/lib/table'

export function RetentionTable({
    dashboardItemId = null,
}: {
    dashboardItemId?: string | number | null
}): JSX.Element | null {
    const logic = retentionTableLogic({ dashboardItemId })
    const {
        results,
        resultsLoading,
        peopleLoading,
        people,
        loadingMore,
        filters: { period, date_to },
    } = useValues(logic)
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
            render: (row) => moment.utc(row.date).format(period === 'h' ? 'MMM D, h a' : 'MMM D'),
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
                        isLatestPeriod && dayIndex === row.values.length - 1
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
                rowClassName={'cursor-pointer'}
                dataSource={results}
                columns={columns}
                rowKey="date"
                loading={resultsLoading}
                onRow={(_, rowIndex: number | undefined) => ({
                    onClick: () => {
                        if (rowIndex !== undefined) {
                            !people[rowIndex] && loadPeople(rowIndex)
                            setModalVisible(true)
                            selectRow(rowIndex)
                        }
                    },
                })}
            />
            {results && (
                <Modal
                    visible={modalVisible}
                    closable={false}
                    onCancel={dismissModal}
                    footer={<Button onClick={dismissModal}>Close</Button>}
                    style={{
                        top: 20,
                        minWidth: results[selectedRow]?.values[0]?.count === 0 ? '10%' : '90%',
                        fontSize: 16,
                    }}
                    title={results[selectedRow] ? moment.utc(results[selectedRow].date).format('MMMM D, YYYY') : ''}
                >
                    {results && !peopleLoading ? (
                        <div>
                            {results[selectedRow]?.values[0]?.count === 0 ? (
                                <span>No users during this period.</span>
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
                                                <td />
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
                                                (people.result as any[]).map((personAppearances) => (
                                                    <tr key={personAppearances.person.id}>
                                                        <td className="text-overflow" style={{ minWidth: 200 }}>
                                                            <Link to={`/person_by_id/${personAppearances.person.id}`}>
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
                                            <Button type="primary" onClick={() => loadMorePeople()}>
                                                {loadingMore ? <Spin /> : 'Load More People'}
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

const renderPercentage = (value: number, total: number, latest = false): JSX.Element => {
    const _percentage = total > 0 ? (100.0 * value) / total : 0
    const backgroundColor = `hsl(212, 63%, ${30 + (100 - _percentage) * 0.65}%)`
    const color = _percentage >= 65 ? 'hsl(0, 0%, 80%)' : undefined

    const numberCell = (
        <div style={{ backgroundColor, color }} className={`percentage-cell${latest ? ' period-in-progress' : ''}`}>
            {_percentage.toFixed(1)}%{latest && '*'}
        </div>
    )
    return latest ? <Tooltip title="Period in progress">{numberCell}</Tooltip> : numberCell
}

const periodIsLatest = (date_to: string, period: string): boolean => {
    if (!date_to) {
        return true
    }

    const curr = moment(date_to)
    if (
        (period == 'Hour' && curr.isSame(moment(), 'hour')) ||
        (period == 'Day' && curr.isSame(moment(), 'day')) ||
        (period == 'Week' && curr.isSame(moment(), 'week')) ||
        (period == 'Month' && curr.isSame(moment(), 'month'))
    ) {
        return true
    } else {
        return false
    }
}
