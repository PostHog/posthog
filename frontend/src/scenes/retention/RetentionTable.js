import React, { useRef, useState } from 'react'
import { useValues, useActions } from 'kea'
import { Table } from 'antd'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DownOutlined } from '@ant-design/icons'
import { entityFilterLogic } from 'scenes/trends/ActionFilter/entityFilterLogic'
import { ActionFilterDropdown } from 'scenes/trends/ActionFilter/ActionFilterDropdown'

export function RetentionTable({ logic }) {
    const node = useRef()
    const [open, setOpen] = useState(false)
    const { retention, retentionLoading, startEntity, filters } = useValues(logic)
    const { setFilters } = useActions(logic)

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
            render: (row) => row.values[0],
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
                    return renderPercentage(row.values[dayIndex], row.values[0])
                },
            })
        })
    }

    return (
        <>
            <PropertyFilters pageKey="RetentionTable" />
            <div>
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
            />
        </>
    )
}

const renderPercentage = (value, total) => {
    const percentage = total > 0 ? (100.0 * value) / total : 100
    const backgroundColor = `hsl(212, 63%, ${30 + (100 - percentage) * 0.65}%)`
    const color = percentage >= 65 ? 'hsl(0, 0%, 80%)' : undefined
    return (
        <div style={{ backgroundColor, color }} className="percentage-cell">
            {percentage.toFixed(1)}%
        </div>
    )
}
