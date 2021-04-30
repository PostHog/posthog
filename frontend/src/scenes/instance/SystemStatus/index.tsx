import './index.scss'

import React from 'react'
import { Alert, Table, Tag, Card } from 'antd'
import { systemStatusLogic } from './systemStatusLogic'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
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

export function SystemStatus(): JSX.Element {
    const { systemStatus, systemStatusLoading, error } = useValues(systemStatusLogic)
    const { configOptions, preflight, preflightLoading, siteUrlMisconfigured } = useValues(preflightLogic)

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
        <div className="system-status-scene">
            <PageHeader
                title="System Status"
                caption="Here you can find all the critical runtime details about your PostHog installation."
            />
            {error && (
                <Alert
                    message="Something went wrong"
                    description={error || <span>An unknown error occurred. Please try again or contact us.</span>}
                    type="error"
                    showIcon
                />
            )}
            {siteUrlMisconfigured && (
                <Alert
                    message="Misconfiguration detected"
                    description={
                        <>
                            Your <code>SITE_URL</code> environment variable seems misconfigured. Your{' '}
                            <code>SITE_URL</code> is set to <b>{RenderValue(preflight?.site_url)}</b> but you're
                            currently browsing this page from{' '}
                            <b>
                                <code>{window.location.origin}</code>
                            </b>
                            . In order for PostHog to work properly, please set this to the origin where your instance
                            is hosted.{' '}
                            <a
                                target="_blank"
                                rel="noopener"
                                href="https://posthog.com/docs/configuring-posthog/environment-variables?utm_medium=in-product&utm_campaign=system-status-site-url-misconfig"
                            >
                                Learn more <IconExternalLink />
                            </a>
                        </>
                    }
                    showIcon
                    type="warning"
                    style={{ marginBottom: 32 }}
                />
            )}
            <Card>
                <h3 className="l3">Key metrics</h3>
                <Table
                    className="system-status-table"
                    size="small"
                    rowKey="metric"
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    dataSource={systemStatus}
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
            <Card style={{ marginTop: 32 }}>
                <h3 className="l3">Configuration options</h3>
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
        </div>
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
