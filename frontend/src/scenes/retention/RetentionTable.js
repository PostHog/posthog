import React from 'react'
import { useValues, useActions } from 'kea'
import { Table } from 'antd'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DatePicker, Select, Row } from 'antd'
import { dateOptions } from './retentionTableLogic'

export function RetentionTable({ logic }) {
    const { retention, retentionLoading, selectedDate, period } = useValues(logic)
    const { dateChanged, setPeriod } = useActions(logic)

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
            <Row>
                <div>
                    <span style={{ marginRight: 5 }}>Start Day:</span>
                    <DatePicker
                        className="mb-2"
                        value={selectedDate}
                        onChange={dateChanged}
                        allowClear={false}
                    ></DatePicker>
                </div>
                <div>
                    <span style={{ marginLeft: 10, marginRight: 5 }}>Period:</span>
                    <Select
                        value={dateOptions[period]}
                        onChange={(value) => setPeriod(value)}
                        dropdownMatchSelectWidth={true}
                    >
                        {Object.entries(dateOptions).map(([key, value]) => (
                            <Select.Option key={key} value={key}>
                                {value}
                            </Select.Option>
                        ))}
                    </Select>
                </div>
            </Row>
            <PropertyFilters pageKey="RetentionTable" />

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
    const percentage = total > 0 ? (100.0 * value) / total : 0
    const backgroundColor = `hsl(212, 63%, ${30 + (100 - percentage) * 0.65}%)`
    const color = percentage >= 65 ? 'hsl(0, 0%, 80%)' : undefined
    return (
        <div style={{ backgroundColor, color }} className="percentage-cell">
            {percentage.toFixed(1)}%
        </div>
    )
}
