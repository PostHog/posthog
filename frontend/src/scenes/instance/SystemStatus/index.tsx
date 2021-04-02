import './index.scss'

import React from 'react'
import { Alert, Table, Tag, Card } from 'antd'
import { systemStatusLogic } from './systemStatusLogic'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'

const columns = [
    {
        title: 'Metric',
        dataIndex: 'metric',
        className: 'metric-column',
    },
    {
        title: 'Value',
        dataIndex: 'value',
        render: function RenderValue(value: any) {
            if (typeof value === 'boolean') {
                return <Tag color={value ? 'success' : 'error'}>{value ? 'Yes' : 'No'}</Tag>
            }
            if (value === null || value === undefined) {
                return <Tag>Unknown</Tag>
            }
            return value.toString()
        },
    },
]

export function SystemStatus(): JSX.Element {
    const { systemStatus, systemStatusLoading, error } = useValues(systemStatusLogic)
    return (
        <div className="system-status-scene">
            <PageHeader
                title="System Status"
                caption="Here you can find all the critical runtime details about your PostHog installation."
            />
            {error && (
                <Alert
                    message={error || <span>Something went wrong. Please try again or contact us.</span>}
                    type="error"
                />
            )}
            <Card>
                <Table
                    className="system-status-table"
                    size="small"
                    rowKey="metric"
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    dataSource={systemStatus}
                    columns={columns}
                    loading={systemStatusLoading}
                />
            </Card>
        </div>
    )
}
