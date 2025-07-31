import { useValues } from 'kea'

import { LemonTable } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { SystemStatusRow, SystemStatusSubrows } from '~/types'

import { RenderMetricValue } from './RenderMetricValue'
import { systemStatusLogic } from './systemStatusLogic'

const METRIC_KEY_TO_INTERNAL_LINK = {
    async_migrations_ok: '/instance/async_migrations',
}

function RenderMetric(_: any, systemStatusRow: SystemStatusRow): JSX.Element {
    return (
        <span>
            {systemStatusRow.metric}{' '}
            {METRIC_KEY_TO_INTERNAL_LINK[systemStatusRow.key] ? (
                <Link to={METRIC_KEY_TO_INTERNAL_LINK[systemStatusRow.key]}>
                    <IconOpenInNew style={{ verticalAlign: 'middle' }} />
                </Link>
            ) : null}
        </span>
    )
}

export function OverviewTab(): JSX.Element {
    const { overview, systemStatusLoading } = useValues(systemStatusLogic)

    return (
        <LemonTable
            className="system-status-table"
            rowKey="metric"
            dataSource={overview}
            columns={[
                {
                    title: 'Metric',
                    className: 'metric-column',
                    render: RenderMetric,
                },
                {
                    title: 'Value',
                    render: RenderMetricValue,
                },
            ]}
            loading={systemStatusLoading}
            expandable={{
                expandedRowRender: function renderExpand(row) {
                    return row.subrows?.rows.length ? <Subrows {...row.subrows} /> : null
                },
                rowExpandable: (row) => !!row.subrows?.rows.length,
            }}
        />
    )
}

function Subrows(props: SystemStatusSubrows): JSX.Element {
    return (
        <LemonTable
            dataSource={props.rows}
            columns={props.columns.map((title, dataIndex) => ({ title, dataIndex }))}
            embedded
        />
    )
}
