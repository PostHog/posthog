import { LemonTableColumns } from '@posthog/lemon-ui'

import type { HealthRowApi, HealthStatusEnumApi } from './generated/api.schemas'
import { formatApdex, formatMs, formatPercent, formatRate } from './healthDisplay'
import { HealthStatusTag } from './HealthStatusTag'

/** Status, requests, errors, p95, and Apdex: the columns every health table shows for a row. */
export function healthColumns<T extends { status: HealthStatusEnumApi; health: HealthRowApi }>(): LemonTableColumns<T> {
    return [
        {
            title: 'Status',
            key: 'status',
            render: (_, row) => <HealthStatusTag status={row.status} />,
        },
        {
            title: 'Requests',
            key: 'request_rate',
            align: 'right',
            render: (_, row) => <span className="font-mono">{formatRate(row.health.request_rate)}</span>,
        },
        {
            title: 'Errors',
            key: 'error_rate',
            align: 'right',
            render: (_, row) => <span className="font-mono">{formatPercent(row.health.error_rate)}</span>,
        },
        {
            title: 'p95',
            key: 'p95_ms',
            align: 'right',
            render: (_, row) => <span className="font-mono">{formatMs(row.health.p95_ms)}</span>,
        },
        {
            title: 'Apdex',
            key: 'apdex',
            align: 'right',
            tooltip:
                'Share of satisfied requests, from 0 to 1. A request under 500 ms counts in full, one under 2 s counts half, and slower or failed requests count as zero.',
            render: (_, row) => <span className="font-mono">{formatApdex(row.health.apdex)}</span>,
        },
    ]
}
