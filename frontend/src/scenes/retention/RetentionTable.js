import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Modal, Button, Spin } from 'antd'
import { percentage } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { retentionTableLogic } from './retentionTableLogic'
import './RetentionTable.scss'
import moment from 'moment'

export function RetentionTable({ dashboardItemId = null }) {
    const logic = retentionTableLogic({ dashboardItemId })
    const {
        results,
        resultsLoading,
        peopleLoading,
        people,
        loadingMore,
        filters: { period },
    } = useValues(logic)
    const { loadPeople, loadMore } = useActions(logic)
    const [modalVisible, setModalVisible] = useState(false)
    const [selectedRow, selectRow] = useState(0)

    let columns = [
        {
            title: 'Date',
            key: 'date',
            render: (row) => moment(row.date).format(period === 'h' ? 'MMM D, h a' : 'MMM D'),
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
        results[0].values.forEach((_, dayIndex) => {
            columns.push({
                title: results[dayIndex].label,
                key: `day::${dayIndex}`,
                render: (row) => {
                    if (dayIndex >= row.values.length) {
                        return ''
                    }
                    return renderPercentage(row.values[dayIndex]['count'], row.values[0]['count'])
                },
            })
        })
    }

    function dismissModal() {
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
                onRow={(_, rowIndex) => {
                    return {
                        onClick: () => {
                            !people[rowIndex] && loadPeople(rowIndex)
                            setModalVisible(true)
                            selectRow(rowIndex)
                        },
                    }
                }}
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
                    title={results[selectedRow]?.date}
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
                                                    results[selectedRow]?.values.map((data, index) => (
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
                                                people.result.map((personAppearances) => (
                                                    <tr key={personAppearances.person.id}>
                                                        <td className="text-overflow" style={{ minWidth: 200 }}>
                                                            <Link to={`/person_by_id/${personAppearances.person.id}`}>
                                                                {personAppearances.person.name}
                                                            </Link>
                                                        </td>
                                                        {personAppearances.appearances.map((appearance, index) => {
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
                                                        })}
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
                                        {people.next && (
                                            <Button type="primary" onClick={() => loadMore(selectedRow)}>
                                                {loadingMore ? <Spin /> : 'Load More People'}
                                            </Button>
                                        )}
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

const renderPercentage = (value, total) => {
    const percentage = total > 0 ? (100.0 * value) / total : 0
    const backgroundColor = `hsl(212, 63%, ${30 + (100 - percentage) * 0.65}%)`
    const color = percentage >= 65 ? 'hsl(0, 0%, 80%)' : undefined
    return (
        <div style={{ backgroundColor, color }} className="percentage-cell">
            {percentage.toFixed(1)}%
        </div>
    )
}
