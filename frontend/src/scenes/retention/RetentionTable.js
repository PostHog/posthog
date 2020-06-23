import React from 'react'
import { useValues } from 'kea'
import { Table } from 'antd'

export function RetentionTable({ logic }) {
    const { retention, retentionLoading } = useValues(logic)

    let columns = [
        {
            title: 'Cohort',
            key: 'cohort',
            render: row => row.date,
        },
        {
            title: 'Users',
            key: 'users',
            render: row => row.values[0],
        },
    ]

    if (!retentionLoading) {
        retention.data[0].values.forEach((_, dayIndex) => {
            columns.push({
                title: retention.data[dayIndex].label,
                key: `day::${dayIndex}`,
                render: row => {
                    if (dayIndex >= row.values.length) {
                        return ''
                    }
                    return renderPercentage(row.values[dayIndex], row.values[0])
                },
            })
        })
    }

    return (
        <Table
            data-attr="retention-table"
            size="small"
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            rowClassName="cursor-pointer"
            dataSource={retention.data}
            columns={columns}
            loading={retentionLoading}
        />
    )
}

const renderPercentage = (value, total) => {
    if (total === 0) {
        return '100.0%'
    }
    const percentage = (100.0 * value) / total
    return `${percentage.toFixed(1)}%`
}
