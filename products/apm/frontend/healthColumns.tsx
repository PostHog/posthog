import { LemonTableColumns } from '@posthog/lemon-ui'

import { ErrorRateBar } from './ErrorRateBar'
import type { HealthRowApi, HealthStatusEnumApi } from './generated/api.schemas'
import { compareNullable, formatMs, formatRate } from './healthDisplay'
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
            sorter: (a, b) => compareNullable(a.health.request_rate, b.health.request_rate),
            render: (_, row) => <span className="font-mono">{formatRate(row.health.request_rate)}</span>,
        },
        {
            title: 'Error rate',
            key: 'error_rate',
            align: 'right',
            sorter: (a, b) => compareNullable(a.health.error_rate, b.health.error_rate),
            render: (_, row) => <ErrorRateBar errorRate={row.health.error_rate} status={row.status} />,
        },
        {
            title: 'p95',
            key: 'p95_ms',
            align: 'right',
            sorter: (a, b) => compareNullable(a.health.p95_ms, b.health.p95_ms),
            render: (_, row) => <span className="font-mono">{formatMs(row.health.p95_ms)}</span>,
        },
    ]
}
