import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type {
    TraceListItemApi,
    TracePersonApi,
    TracePreviewApi,
    TraceSentimentApi,
} from '../../../generated/api.schemas'
import { PartialTotal } from '../../shared/components/PartialTotal'
import { formatCostUsd, formatLatencyMs, formatTokenCounts } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import type { TraceCellLoad, TraceCellStatus } from '../types'
import { TraceCellValue } from './TraceCellValue'
import { TraceErrorsCell } from './TraceErrorsCell'
import { TraceNameCell } from './TraceNameCell'
import { TracePersonCell } from './TracePersonCell'
import { TracePreviewCell } from './TracePreviewCell'
import { TraceReviewCell } from './TraceReviewCell'
import { TraceSentimentCell } from './TraceSentimentCell'
import { TraceToolsCell } from './TraceToolsCell'

export interface TracesTableCells {
    previews: ReadonlyMap<string, TraceCellLoad<TracePreviewApi>>
    people: ReadonlyMap<string, TraceCellLoad<TracePersonApi | null>>
    sentiments: ReadonlyMap<string, TraceCellLoad<TraceSentimentApi | null>>
}

export interface TracesTableColumnsOptions {
    linkTo: (item: TraceListItemApi) => string
    cells: TracesTableCells
}

// The cells are read right after the row lands, so a row with no entry yet is about to load.
function statusOf(load: TraceCellLoad<unknown> | undefined): TraceCellStatus {
    return load?.status ?? 'loading'
}

function valueOf<T>(load: TraceCellLoad<T | null> | undefined): T | null {
    return load?.status === 'ready' ? load.value : null
}

function TotalValue({ value, partial }: { value: string | null; partial: boolean }): JSX.Element {
    if (value === null) {
        return <TraceCellValue>{null}</TraceCellValue>
    }
    return <PartialTotal partial={partial}>{value}</PartialTotal>
}

export function tracesTableColumns({
    linkTo,
    cells: { previews, people, sentiments },
}: TracesTableColumnsOptions): LemonTableColumns<TraceListItemApi> {
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
            title: 'Person',
            key: 'person',
            render: (_, { id }) => (
                <TracePersonCell person={valueOf(people.get(id))} status={statusOf(people.get(id))} />
            ),
        },
        {
            title: 'Input',
            key: 'input',
            render: (_, { id }) => (
                <TracePreviewCell
                    text={valueOf(previews.get(id))?.input ?? null}
                    missingReason={valueOf(previews.get(id))?.inputMissingReason ?? null}
                    status={statusOf(previews.get(id))}
                />
            ),
        },
        {
            title: 'Output',
            key: 'output',
            render: (_, { id }) => (
                <TracePreviewCell
                    text={valueOf(previews.get(id))?.output ?? null}
                    missingReason={valueOf(previews.get(id))?.outputMissingReason ?? null}
                    status={statusOf(previews.get(id))}
                />
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
            title: 'Sentiment',
            key: 'sentiment',
            render: (_, { id }) => (
                <TraceSentimentCell sentiment={valueOf(sentiments.get(id))} status={statusOf(sentiments.get(id))} />
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
