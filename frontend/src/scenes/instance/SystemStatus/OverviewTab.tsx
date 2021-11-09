import React from 'react'
import { Table, Tag, Card } from 'antd'
import { systemStatusLogic } from './systemStatusLogic'
import { useValues } from 'kea'
import { SystemStatusSubrows } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { IconExternalLink } from 'lib/components/icons'

function RenderValue(value: any): JSX.Element | string {
    if (typeof value === 'boolean') {
        return <Tag color={value ? 'success' : 'error'}>{value ? 'Yes' : 'No'}</Tag>
    }
    if (value === null || value === undefined || value === '') {
        return <Tag>Unknown</Tag>
    }
    return value.toString()
}

export function OverviewTab(): JSX.Element {
    const { overview, systemStatusLoading } = useValues(systemStatusLogic)
    const { configOptions, preflightLoading } = useValues(preflightLogic)

    const columns = [
        {
            title: 'Metric',
            dataIndex: 'metric',
            className: 'metric-column',
        },
        {
            title: 'Value',
            dataIndex: 'value',
            render: RenderValue,
        },
    ]

    return (
        <>
            <Card>
                <h3 className="l3">Key metrics</h3>
                <Table
                    className="system-status-table"
                    size="small"
                    rowKey="metric"
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    dataSource={overview}
                    columns={columns}
                    loading={systemStatusLoading}
                    expandable={{
                        expandedRowRender: function renderExpand(row) {
                            return row.subrows ? <Subrows {...row.subrows} /> : null
                        },
                        rowExpandable: (row) => !!row.subrows && row.subrows.rows.length > 0,
                        expandRowByClick: true,
                    }}
                />

                <h3 className="l3" style={{ marginTop: 32 }}>
                    Configuration options
                </h3>
                <p>
                    <a
                        href="https://posthog.com/docs/self-host#Configure?utm_medium=in-product"
                        rel="noopener"
                        target="_blank"
                    >
                        Learn more <IconExternalLink style={{ verticalAlign: 'middle' }} />
                    </a>
                </p>
                <Table
                    className="system-config-table"
                    size="small"
                    rowKey="metric"
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    dataSource={configOptions}
                    columns={columns}
                    loading={preflightLoading}
                />
            </Card>
        </>
    )
}

function Subrows(props: SystemStatusSubrows): JSX.Element {
    return (
        <Table
            rowKey="metric"
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            dataSource={props.rows}
            columns={props.columns.map((title, dataIndex) => ({ title, dataIndex }))}
        />
    )
}
