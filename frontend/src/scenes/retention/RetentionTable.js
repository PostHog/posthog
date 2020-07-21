import React, { useRef, useState } from 'react'
import { useValues, useActions } from 'kea'
import { Table, Modal, Button, Spin } from 'antd'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { percentage } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { DownOutlined } from '@ant-design/icons'
import { entityFilterLogic } from 'scenes/trends/ActionFilter/entityFilterLogic'
import { ActionFilterDropdown } from 'scenes/trends/ActionFilter/ActionFilterDropdown'

export function RetentionTable({ logic }) {
    const node = useRef()
    const [open, setOpen] = useState(false)
    const { retention, retentionLoading, peopleLoading, people, loadingMore, startEntity, filters } = useValues(logic)
    const { loadPeople, loadMore, setFilters } = useActions(logic)
    const [modalVisible, setModalVisible] = useState(false)
    const [selectedRow, selectRow] = useState(0)

    const entityLogic = entityFilterLogic({
        setFilters: (filters) => {
            setFilters(filters)
            setOpen(false)
        },
        filters: filters,
        typeKey: 'retention-table',
        singleMode: true,
    })

    let columns = [
        {
            title: 'Cohort',
            key: 'cohort',
            render: (row) => row.date,
        },
        {
            title: 'Users',
            key: 'users',
            render: (row) => row.values[0]['count'],
        },
    ]

    if (!retentionLoading && retention.data) {
        retention.data[0].values.forEach((_, dayIndex) => {
            columns.push({
                title: retention.data[dayIndex].label,
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
            <PropertyFilters pageKey="RetentionTable" />
            <div className="mb-4">
                <span>Target Event: </span>
                <button
                    ref={node}
                    className="filter-action btn btn-sm btn-light"
                    type="button"
                    onClick={() => setOpen(!open)}
                    style={{
                        fontWeight: 500,
                    }}
                >
                    {startEntity?.name || 'Select action'}
                    <DownOutlined style={{ marginLeft: '3px', color: 'rgba(0, 0, 0, 0.25)' }} />
                </button>
                {open && (
                    <ActionFilterDropdown
                        logic={entityLogic}
                        onClickOutside={(e) => {
                            if (node.current.contains(e.target)) {
                                return
                            }
                            setOpen(false)
                        }}
                    />
                )}
            </div>
            <Table
                data-attr="retention-table"
                size="small"
                className="retention-table"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowClassName="cursor-pointer"
                dataSource={retention.data}
                columns={columns}
                loading={retentionLoading}
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
            {retention.data && (
                <Modal
                    visible={modalVisible}
                    closable={false}
                    onCancel={dismissModal}
                    footer={<Button onClick={dismissModal}>Close</Button>}
                    style={{
                        top: 20,
                        minWidth: retention?.data[selectedRow]?.values[0]?.count === 0 ? '10%' : '90%',
                        fontSize: 16,
                    }}
                    title={retention.data[selectedRow].date}
                >
                    {retention && !peopleLoading ? (
                        <div>
                            {retention?.data[selectedRow]?.values[0]?.count === 0 ? (
                                <span>No users during this period.</span>
                            ) : (
                                <div>
                                    <table className="table table-bordered table-fixed">
                                        <tbody>
                                            <tr>
                                                <th />
                                                {retention.data &&
                                                    retention.data
                                                        .slice(0, retention.data[selectedRow].values.length)
                                                        .map((data, index) => <th key={index}>{data.label}</th>)}
                                            </tr>
                                            <tr>
                                                <td />
                                                {retention.data &&
                                                    retention.data[selectedRow].values.map((data, index) => (
                                                        <td key={index}>
                                                            {data.count}&nbsp;{' '}
                                                            {data.count > 0 && (
                                                                <span>
                                                                    (
                                                                    {percentage(
                                                                        data.count /
                                                                            retention.data[selectedRow].values[0][
                                                                                'count'
                                                                            ]
                                                                    )}
                                                                    )
                                                                </span>
                                                            )}
                                                        </td>
                                                    ))}
                                            </tr>
                                            {people[selectedRow] &&
                                                people[selectedRow].map((person) => (
                                                    <tr key={person.id}>
                                                        <td className="text-overflow" style={{ minWidth: 200 }}>
                                                            <Link to={`/person_by_id/${person.id}`}>{person.name}</Link>
                                                        </td>
                                                        {retention.data[selectedRow].values.map((step, index) => {
                                                            return (
                                                                <td
                                                                    key={index}
                                                                    className={
                                                                        step.people.indexOf(person.id) > -1
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
                                        {retention.data[selectedRow].values.some((element) => element.next) && (
                                            <Button type="primary" onClick={() => loadMore(selectedRow)}>
                                                {loadingMore ? <Spin /> : 'Load More People'}
                                            </Button>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    ) : (
                        <Spin></Spin>
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
