import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { BreakdownList } from '../../shared/components/BreakdownList'
import { ExampleItem, ExampleList } from '../../shared/components/ExampleList'
import { StatTiles } from '../../shared/components/StatTiles'
import { VolumeCell } from '../../shared/components/VolumeCell'
import { formatLatencyMs } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import type { ErrorDetail as ErrorDetailData, ErrorExample } from '../errorsQueries'

export interface ErrorDetailProps {
    error: string
    /** Null while loading. */
    detail: ErrorDetailData | null
    labels: string[]
    activeExampleKey: string | null
    onOpenExample: (example: ErrorExample) => void
    onFilterModel: (model: string) => void
}

function toItem(example: ErrorExample): ExampleItem {
    return {
        key: example.uuid,
        title: example.name ?? `Trace ${example.traceId.slice(0, 8)}`,
        detail: example.rawError,
        detailTone: 'danger',
        tags: example.model ? [{ label: example.model, type: 'muted' }] : [],
        timestamp: example.timestamp,
        metric: example.latency !== null ? formatLatencyMs(example.latency * 1000) : null,
    }
}

export function ErrorDetail({
    error,
    detail,
    labels,
    activeExampleKey,
    onOpenExample,
    onFilterModel,
}: ErrorDetailProps): JSX.Element {
    const summary = detail?.summary ?? null
    const number = (value: number | undefined): string | null =>
        detail === null ? null : humanFriendlyNumber(value ?? 0)
    const examplesByKey = new Map((detail?.examples ?? []).map((example) => [example.uuid, example]))

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-start gap-2 rounded border border-primary bg-surface-secondary p-3">
                <pre className="ph-no-capture m-0 max-h-40 min-w-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words font-mono text-sm text-danger">
                    {error}
                </pre>
                <LemonButton
                    size="xsmall"
                    icon={<IconCopy />}
                    tooltip="Copy error"
                    onClick={() => void copyToClipboard(error, 'error')}
                    data-attr="ai-observability-error-drawer-copy"
                />
            </div>
            <StatTiles
                tiles={[
                    { label: 'Occurrences', value: number(summary?.occurrences), tone: 'danger' },
                    { label: 'Traces', value: number(summary?.traces) },
                    { label: 'Sessions', value: number(summary?.sessions) },
                    { label: 'Users', value: number(summary?.users) },
                    {
                        label: 'First seen',
                        value: detail === null ? null : summary ? <ShortTimestamp time={summary.firstSeen} /> : '-',
                    },
                    {
                        label: 'Last seen',
                        value: detail === null ? null : summary ? <ShortTimestamp time={summary.lastSeen} /> : '-',
                    },
                ]}
            />
            {summary ? (
                <VolumeCell
                    values={summary.volume}
                    labels={labels}
                    name="Occurrences"
                    color="danger"
                    className="h-16 w-full"
                />
            ) : null}
            <div className="grid grid-cols-1 gap-4 @md:grid-cols-2 sm:grid-cols-2">
                <BreakdownList
                    title="Models"
                    rows={detail?.models ?? null}
                    emptyText="No model recorded on these events."
                    onSelect={onFilterModel}
                    data-attr="ai-observability-error-drawer-model"
                />
                <BreakdownList
                    title="Most affected people"
                    rows={detail?.users ?? null}
                    emptyText="No people recorded on these events."
                    data-attr="ai-observability-error-drawer-person"
                />
            </div>
            <ExampleList
                title="Recent occurrences"
                examples={detail ? detail.examples.map(toItem) : null}
                activeKey={activeExampleKey}
                emptyText="No occurrences with a trace in this date range."
                onOpen={(item) => {
                    const example = examplesByKey.get(item.key)
                    if (example) {
                        onOpenExample(example)
                    }
                }}
                data-attr="ai-observability-error-drawer-example"
            />
        </div>
    )
}
