import { LemonTableColumns } from '@posthog/lemon-ui'

import { ErrorRateBar } from './ErrorRateBar'
import type { HealthRowApi, HealthStatusEnumApi } from './generated/api.schemas'
import { compareNullable, formatApdex, formatMs, formatRateIn, tableRateUnit } from './healthDisplay'
import { HealthStatusTag } from './HealthStatusTag'

/**
 * Status, requests, errors, p95, and Apdex: the columns every health table shows for a row.
 * Takes the rows so the request rates share one unit, picked from the busiest row.
 */
export function healthColumns<T extends { status: HealthStatusEnumApi; health: HealthRowApi }>(
    rows: T[]
): LemonTableColumns<T> {
    const rateUnit = tableRateUnit(rows.map((row) => row.health.request_rate))
    return [
        {
            title: 'Status',
            key: 'status',
            render: (_, row) => <HealthStatusTag status={row.status} />,
        },
        {
            title: `Requests (${rateUnit})`,
            key: 'request_rate',
            align: 'right',
            sorter: (a, b) => compareNullable(a.health.request_rate, b.health.request_rate),
            render: (_, row) => <span className="font-mono">{formatRateIn(row.health.request_rate, rateUnit)}</span>,
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
        {
            title: 'Apdex',
            key: 'apdex',
            align: 'right',
            tooltip:
                'Share of satisfied requests, from 0 to 1. A request under 500 ms counts in full, one under 2 s counts half, and slower or failed requests count as zero.',
            sorter: (a, b) => compareNullable(a.health.apdex ?? null, b.health.apdex ?? null),
            render: (_, row) => <span className="font-mono">{formatApdex(row.health.apdex)}</span>,
        },
    ]
}
