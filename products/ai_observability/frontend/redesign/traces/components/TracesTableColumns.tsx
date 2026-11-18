import { Tooltip } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type { TraceListItemApi } from '../../../generated/api.schemas'
import { formatCostUsd, formatLatencyMs, formatTokenCounts } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import { TraceErrorsCell } from './TraceErrorsCell'
import { TraceNameCell } from './TraceNameCell'
import { TraceReviewCell } from './TraceReviewCell'
import { TraceToolsCell } from './TraceToolsCell'

export interface TracesTableColumnsOptions {
    linkTo: (item: TraceListItemApi) => string
}

function TotalValue({ value, partial }: { value: string | null; partial: boolean }): JSX.Element {
    if (value === null) {
        return <span className="text-muted">-</span>
    }
    if (!partial) {
        return <span className="whitespace-nowrap">{value}</span>
    }
    return (
        <Tooltip title="Partial. This trace has more steps than the list reads, so its totals, errors and tools come from its earliest steps only.">
            <span className="cursor-help whitespace-nowrap underline decoration-dotted">{value}</span>
        </Tooltip>
    )
}

export function tracesTableColumns({ linkTo }: TracesTableColumnsOptions): LemonTableColumns<TraceListItemApi> {
    return [
        {
            title: 'Time',
            key: 'time',
            render: (_, item) => <ShortTimestamp time={item.createdAt} />,
        },
        {
            title: 'Name',
            key: 'name',
            render: (_, item) => (
                <TraceNameCell name={item.name} href={linkTo(item)} isSupportTrace={item.isSupportTrace} />
            ),
        },
        {
            title: 'Errors',
            key: 'errors',
            render: (_, item) => (
                <TraceErrorsCell firstError={item.firstError} errorCount={item.errorCount} hasError={item.hasError} />
            ),
        },
        {
            title: 'Latency',
            key: 'latency',
            align: 'right',
            render: (_, { totals, totalsPartial }) => (
                <TotalValue
                    value={totals.latencyMs !== null ? formatLatencyMs(totals.latencyMs) : null}
                    partial={totalsPartial}
                />
            ),
        },
        {
            title: 'Tokens',
            key: 'tokens',
            align: 'right',
            render: (_, { totals, totalsPartial }) => (
                <TotalValue
                    value={formatTokenCounts(totals.inputTokens, totals.outputTokens)}
                    partial={totalsPartial}
                />
            ),
        },
        {
            title: 'Cost',
            key: 'cost',
            align: 'right',
            render: (_, { totals, totalsPartial }) => (
                <TotalValue
                    value={totals.costUsd !== null ? formatCostUsd(totals.costUsd) : null}
                    partial={totalsPartial}
                />
            ),
        },
        {
            title: 'Tools',
            key: 'tools',
            render: (_, item) => <TraceToolsCell tools={item.toolsCalled} />,
        },
        {
            title: 'Review',
            key: 'review',
            render: (_, item) => <TraceReviewCell review={item.review} />,
        },
    ]
}
