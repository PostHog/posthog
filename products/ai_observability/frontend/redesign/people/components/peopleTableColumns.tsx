import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { VolumeCell } from '../../shared/components/VolumeCell'
import { formatCostUsd, formatLatencyMs } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import type { PersonRow } from '../peopleQueries'
import { personLabel } from '../personLabel'
import { ErrorRateTag } from './ErrorRateTag'

export function peopleTableColumns(labels: string[]): LemonTableColumns<PersonRow> {
    return [
        {
            title: 'Person',
            key: 'person',
            width: '25%',
            render: (_, row) => (
                <div className="ph-no-capture flex min-w-0 flex-col gap-0.5 py-1">
                    <span className="truncate text-sm font-semibold">{personLabel(row)}</span>
                    {personLabel(row) !== row.distinctId ? (
                        <span className="truncate font-mono text-xs text-secondary">{row.distinctId}</span>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Volume',
            key: 'volume',
            align: 'right',
            tooltip: 'Generations over the date range',
            render: (_, row) => (
                <div className="flex justify-end">
                    <VolumeCell values={row.volume} labels={labels} name="Generations" />
                </div>
            ),
        },
        {
            title: 'Traces',
            key: 'traces',
            align: 'right',
            sorter: (a, b) => a.traces - b.traces,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.traces)}</span>,
        },
        {
            title: 'Generations',
            key: 'generations',
            align: 'right',
            sorter: (a, b) => a.generations - b.generations,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.generations)}</span>,
        },
        {
            title: 'Errors',
            key: 'errors',
            align: 'right',
            tooltip: 'Generations that ended in an error, and their share of all generations',
            sorter: (a, b) => a.errors / Math.max(a.generations, 1) - b.errors / Math.max(b.generations, 1),
            render: (_, row) => <ErrorRateTag errors={row.errors} total={row.generations} />,
        },
        {
            title: 'Cost',
            key: 'cost',
            align: 'right',
            sorter: (a, b) => a.costUsd - b.costUsd,
            render: (_, row) => <span className="tabular-nums">{formatCostUsd(row.costUsd)}</span>,
        },
        {
            title: 'p95 latency',
            key: 'p95',
            align: 'right',
            sorter: (a, b) => (a.p95LatencySeconds ?? 0) - (b.p95LatencySeconds ?? 0),
            render: (_, row) =>
                row.p95LatencySeconds !== null ? (
                    <span className="tabular-nums">{formatLatencyMs(row.p95LatencySeconds * 1000)}</span>
                ) : (
                    <span className="text-muted">-</span>
                ),
        },
        {
            title: 'Last seen',
            key: 'lastSeen',
            align: 'right',
            sorter: (a, b) => a.lastSeen.localeCompare(b.lastSeen),
            render: (_, row) => <ShortTimestamp time={row.lastSeen} />,
        },
    ]
}
