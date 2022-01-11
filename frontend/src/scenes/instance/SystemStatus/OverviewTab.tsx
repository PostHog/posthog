import React from 'react'
import { Table, Tag, Card } from 'antd'
import { systemStatusLogic } from './systemStatusLogic'
import { useValues } from 'kea'
import { SystemStatusSubrows } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { IconOpenInNew } from 'lib/components/icons'
import { Link } from 'lib/components/Link'
import { humanFriendlyDetailedTime } from 'lib/utils'

interface MetricRow {
    metric: string
    key: string
    value: any
}

const METRIC_KEY_TO_INTERNAL_LINK = {
    async_migrations_ok: '/instance/async_migrations',
}

const TIMESTAMP_VALUES = new Set(['last_event_ingested_timestamp'])

function RenderValue(metricRow: MetricRow): JSX.Element | string {
    const value = metricRow.value

    if (TIMESTAMP_VALUES.has(metricRow.key)) {
        if (new Date(value).getTime() === new Date('1970-01-01T00:00:00').getTime()) {
            return 'Never'
        }
        return humanFriendlyDetailedTime(value)
    }

    if (typeof value === 'boolean') {
        return <Tag color={value ? 'success' : 'error'}>{value ? 'Yes' : 'No'}</Tag>
    }

    if (value === null || value === undefined || value === '') {
        return <Tag>Unknown</Tag>
    }

    return value.toString()
}

function RenderMetric(metricRow: MetricRow): JSX.Element {
    return (
        <span>
            {metricRow.metric}{' '}
            {METRIC_KEY_TO_INTERNAL_LINK[metricRow.key] ? (
                <Link to={METRIC_KEY_TO_INTERNAL_LINK[metricRow.key]}>
                    <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                </Link>
            ) : null}
        </span>
    )
}

export function OverviewTab(): JSX.Element {
    const { overview, systemStatusLoading } = useValues(systemStatusLogic)
    const { configOptions, preflightLoading } = useValues(preflightLogic)

    const columns = [
        {
            title: 'Metric',
            className: 'metric-column',
            render: RenderMetric,
        },
        {
            title: 'Value',
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
                    pagination={false}
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
                        Learn more <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                    </a>
                </p>
                <Table
                    className="system-config-table"
                    size="small"
                    rowKey="metric"
                    pagination={false}
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
            pagination={false}
            dataSource={props.rows}
            columns={props.columns.map((title, dataIndex) => ({ title, dataIndex }))}
        />
    )
}
