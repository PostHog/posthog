import { useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { CloudAgentUsageBucketApi } from '../generated/api.schemas'
import { cloudAgentsUsageLogic } from '../logics/cloudAgentsUsageLogic'
import { formatCost, formatSecondsAsHours } from '../utils/pricing'

export function UsageTable(): JSX.Element {
    const { usage, usageLoading, groupBy } = useValues(cloudAgentsUsageLogic)
    const byDay = groupBy === 'day'

    const columns: LemonTableColumns<CloudAgentUsageBucketApi> = [
        {
            title: byDay ? 'Day' : 'Preset',
            key: 'bucket',
            render: (_, bucket) =>
                byDay ? (
                    <span className="whitespace-nowrap" translate="no">
                        {bucket.key ? dayjs.utc(bucket.key).format('MMM D, YYYY') : 'Unknown'}
                    </span>
                ) : (
                    (bucket.name ?? <span className="text-secondary">No preset</span>)
                ),
        },
        {
            title: 'Runs',
            key: 'runs',
            align: 'right',
            render: (_, bucket) => bucket.usage.runs.toLocaleString('en-US'),
        },
        {
            title: 'Compute',
            key: 'compute',
            align: 'right',
            render: (_, bucket) => formatCost(bucket.usage.compute_usd),
        },
        {
            title: 'Model usage',
            key: 'inference',
            align: 'right',
            render: (_, bucket) => formatCost(bucket.usage.inference_usd),
        },
        {
            title: 'vCPU-hours',
            key: 'vcpu',
            align: 'right',
            render: (_, bucket) => formatSecondsAsHours(bucket.usage.vcpu_seconds),
        },
        {
            title: 'GiB-hours',
            key: 'gib',
            align: 'right',
            render: (_, bucket) => formatSecondsAsHours(bucket.usage.gib_seconds),
        },
        {
            title: 'Total',
            key: 'total',
            align: 'right',
            render: (_, bucket) => <span className="font-semibold">{formatCost(bucket.usage.total_usd)}</span>,
        },
    ]

    return (
        <LemonTable
            dataSource={usage?.buckets ?? []}
            columns={columns}
            rowKey={(bucket) => bucket.key ?? 'none'}
            loading={usageLoading}
            emptyState="No runs in this date range. Choose a longer range to see earlier usage."
            data-attr="cloud-agents-usage-table"
        />
    )
}
