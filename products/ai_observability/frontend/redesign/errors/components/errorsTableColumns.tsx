import { LemonTag } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { VolumeCell } from '../../shared/components/VolumeCell'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import type { ErrorRow } from '../errorsQueries'

export function errorsTableColumns(labels: string[]): LemonTableColumns<ErrorRow> {
    return [
        {
            title: 'Error',
            key: 'error',
            width: '50%',
            render: (_, row) => (
                <div className="flex min-w-0 flex-col gap-1 py-1">
                    {/* Error texts are raw event data, so keep them out of autocapture and replay. */}
                    <span className="ph-no-capture line-clamp-2 font-mono text-sm font-semibold" title={row.error}>
                        {row.error}
                    </span>
                    <span className="flex flex-wrap items-center gap-1 text-xs text-secondary">
                        {row.models.map((model) => (
                            <LemonTag key={model} size="small" type="muted" className="ph-no-capture font-mono">
                                {model}
                            </LemonTag>
                        ))}
                        <span>First seen</span>
                        <ShortTimestamp time={row.firstSeen} />
                    </span>
                </div>
            ),
        },
        {
            title: 'Volume',
            key: 'volume',
            align: 'right',
            tooltip: 'Occurrences over the date range',
            render: (_, row) => (
                <div className="flex justify-end">
                    <VolumeCell values={row.volume} labels={labels} name="Occurrences" color="danger" />
                </div>
            ),
        },
        {
            title: 'Occurrences',
            key: 'occurrences',
            align: 'right',
            tooltip: 'Events that ended in this error',
            sorter: (a, b) => a.occurrences - b.occurrences,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.occurrences)}</span>,
        },
        {
            title: 'Traces',
            key: 'traces',
            align: 'right',
            tooltip: 'Traces with at least one event that ended in this error',
            sorter: (a, b) => a.traces - b.traces,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.traces)}</span>,
        },
        {
            title: 'Sessions',
            key: 'sessions',
            align: 'right',
            sorter: (a, b) => a.sessions - b.sessions,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.sessions)}</span>,
        },
        {
            title: 'Users',
            key: 'users',
            align: 'right',
            tooltip: 'People who hit this error',
            sorter: (a, b) => a.users - b.users,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.users)}</span>,
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
