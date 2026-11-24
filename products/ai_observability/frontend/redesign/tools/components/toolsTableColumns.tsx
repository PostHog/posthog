import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { VolumeCell } from '../../shared/components/VolumeCell'
import { formatLatencyMs } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import type { ToolRow } from '../toolsQueries'
import { TrendCell } from './TrendCell'

export interface ToolsTableColumnsOptions {
    labels: string[]
    /** The p95 latency of all generations, which the Slow filter uses too. */
    slowThresholdSeconds: number | null
}

function LatencyCell({
    seconds,
    slowThreshold,
}: {
    seconds: number | null
    slowThreshold: number | null
}): JSX.Element {
    if (seconds === null) {
        return <span className="text-muted">-</span>
    }
    const label = formatLatencyMs(seconds * 1000)
    if (slowThreshold === null || seconds <= slowThreshold) {
        return <span className="tabular-nums">{label}</span>
    }
    return (
        <Tooltip
            title={`Slower than the p95 of all generations (${formatLatencyMs(slowThreshold * 1000)}), the same threshold as the Slow filter`}
        >
            <span tabIndex={0}>
                <LemonTag type="warning" size="small">
                    {label}
                </LemonTag>
            </span>
        </Tooltip>
    )
}

export function toolsTableColumns({
    labels,
    slowThresholdSeconds,
}: ToolsTableColumnsOptions): LemonTableColumns<ToolRow> {
    return [
        {
            title: 'Tool',
            key: 'tool',
            width: '30%',
            render: (_, row) => (
                <div className="flex min-w-0 flex-col gap-0.5 py-1">
                    <span className="ph-no-capture truncate font-mono text-sm font-semibold">{row.tool}</span>
                    <span className="flex flex-wrap items-center gap-x-1 text-xs text-secondary">
                        <span>First called</span>
                        <ShortTimestamp time={row.firstSeen} />
                        <span aria-hidden>·</span>
                        <span>{`Only tool in ${percentage(row.soloShare, 0)} of calls`}</span>
                    </span>
                </div>
            ),
        },
        {
            title: 'Volume',
            key: 'volume',
            align: 'right',
            tooltip: 'Calls over the date range',
            render: (_, row) => (
                <div className="flex justify-end">
                    <VolumeCell values={row.volume} labels={labels} name="Calls" />
                </div>
            ),
        },
        {
            title: 'Calls',
            key: 'calls',
            align: 'right',
            tooltip: 'Generations that called this tool',
            sorter: (a, b) => a.calls - b.calls,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.calls)}</span>,
        },
        {
            title: 'Trend',
            key: 'trend',
            align: 'right',
            tooltip: 'Change in calls versus the period of the same length before the date range',
            sorter: (a, b) =>
                (a.previousCalls ? a.calls / a.previousCalls : Infinity) -
                (b.previousCalls ? b.calls / b.previousCalls : Infinity),
            render: (_, row) => <TrendCell current={row.calls} previous={row.previousCalls} unit="calls" />,
        },
        {
            title: 'p95 latency',
            key: 'p95',
            align: 'right',
            tooltip: '95% of the generations that called this tool finished faster than this',
            sorter: (a, b) => (a.p95LatencySeconds ?? 0) - (b.p95LatencySeconds ?? 0),
            render: (_, row) => <LatencyCell seconds={row.p95LatencySeconds} slowThreshold={slowThresholdSeconds} />,
        },
        {
            title: 'Traces',
            key: 'traces',
            align: 'right',
            tooltip: 'Traces that called this tool, and their share of all traces',
            sorter: (a, b) => a.traces - b.traces,
            render: (_, row) => (
                <span className="whitespace-nowrap tabular-nums">
                    {humanFriendlyNumber(row.traces)}
                    {row.traceShare !== null ? (
                        <span className="text-secondary">{` · ${percentage(row.traceShare, 0)}`}</span>
                    ) : null}
                </span>
            ),
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
            sorter: (a, b) => a.users - b.users,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.users)}</span>,
        },
    ]
}
