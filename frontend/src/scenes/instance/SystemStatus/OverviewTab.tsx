import React from 'react'
import { Table, Card } from 'antd'
import { MetricRow, systemStatusLogic } from './systemStatusLogic'
import { useValues } from 'kea'
import { SystemStatusSubrows } from '~/types'
import { IconOpenInNew } from 'lib/components/icons'
import { Link } from 'lib/components/Link'
import { RenderMetricValue } from './RenderMetricValue'

const METRIC_KEY_TO_INTERNAL_LINK = {
    async_migrations_ok: '/instance/async_migrations',
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

    const columns = [
        {
            title: 'Metric',
            className: 'metric-column',
            render: RenderMetric,
        },
        {
            title: 'Value',
            render: RenderMetricValue,
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
