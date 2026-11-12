import { LemonTableColumns } from '@posthog/lemon-ui'

import type { HealthRowApi, HealthStatusEnumApi } from './generated/api.schemas'
import { formatMs, formatPercent, formatRate } from './healthDisplay'
import { HealthStatusTag } from './HealthStatusTag'

/** Status, requests, errors, and p95: the columns every health table shows for a row. */
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
    ]
}
