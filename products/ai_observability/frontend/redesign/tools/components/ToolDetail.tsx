import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { BreakdownList } from '../../shared/components/BreakdownList'
import { ExampleItem, ExampleList } from '../../shared/components/ExampleList'
import { StatTiles } from '../../shared/components/StatTiles'
import { VolumeCell } from '../../shared/components/VolumeCell'
import { formatLatencyMs } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import type { ToolDetail as ToolDetailData, ToolExample } from '../toolsQueries'
import { TrendCell } from './TrendCell'

export interface ToolDetailProps {
    /** Null while loading. */
    detail: ToolDetailData | null
    labels: string[]
    activeExampleKey: string | null
    onOpenExample: (example: ToolExample) => void
    onSelectTool: (tool: string) => void
    onFilterModel: (model: string) => void
}

function toItem(example: ToolExample): ExampleItem {
    return {
        key: example.uuid,
        title: example.name ?? `Trace ${example.traceId.slice(0, 8)}`,
        detail: example.otherTools.length > 0 ? `Also called ${example.otherTools.join(', ')}` : null,
        tags: [
            ...(example.isError ? [{ label: 'Error', type: 'danger' as const }] : []),
            ...(example.model ? [{ label: example.model, type: 'muted' as const }] : []),
        ],
        timestamp: example.timestamp,
        metric: example.latency !== null ? formatLatencyMs(example.latency * 1000) : null,
    }
}

export function ToolDetail({
    detail,
    labels,
    activeExampleKey,
    onOpenExample,
    onSelectTool,
    onFilterModel,
}: ToolDetailProps): JSX.Element {
    const summary = detail?.summary ?? null
    const value = <T,>(read: (row: NonNullable<typeof summary>) => T): T | string | null =>
        detail === null ? null : summary ? read(summary) : '-'
    const examplesByKey = new Map((detail?.examples ?? []).map((example) => [example.uuid, example]))

    return (
        <div className="flex flex-col gap-4">
            <StatTiles
                tiles={[
                    { label: 'Calls', value: value((row) => humanFriendlyNumber(row.calls)) },
                    {
                        label: 'Trend',
                        value: value((row) => (
                            <TrendCell current={row.calls} previous={row.previousCalls} unit="calls" />
                        )),
                    },
                    {
                        label: 'p95 latency',
                        value: value((row) =>
                            row.p95LatencySeconds !== null ? formatLatencyMs(row.p95LatencySeconds * 1000) : '-'
                        ),
                    },
                    { label: 'Traces', value: value((row) => humanFriendlyNumber(row.traces)) },
                    { label: 'Users', value: value((row) => humanFriendlyNumber(row.users)) },
                    { label: 'Only tool called', value: value((row) => percentage(row.soloShare, 0)) },
                    { label: 'First called', value: value((row) => <ShortTimestamp time={row.firstSeen} />) },
                    { label: 'Last called', value: value((row) => <ShortTimestamp time={row.lastSeen} />) },
                ]}
            />
            {summary ? (
                <VolumeCell values={summary.volume} labels={labels} name="Calls" className="h-16 w-full" />
            ) : null}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <BreakdownList
                    title="Called alongside"
                    rows={detail?.alongside ?? null}
                    emptyText="Always the only tool called."
                    onSelect={onSelectTool}
                    data-attr="ai-observability-tool-drawer-alongside"
                />
                <BreakdownList
                    title="Models calling it"
                    rows={detail?.models ?? null}
                    emptyText="No model recorded on these generations."
                    onSelect={onFilterModel}
                    data-attr="ai-observability-tool-drawer-model"
                />
            </div>
            <ExampleList
                title="Recent calls"
                examples={detail ? detail.examples.map(toItem) : null}
                activeKey={activeExampleKey}
                emptyText="No calls with a trace in this date range."
                onOpen={(item) => {
                    const example = examplesByKey.get(item.key)
                    if (example) {
                        onOpenExample(example)
                    }
                }}
                data-attr="ai-observability-tool-drawer-example"
            />
        </div>
    )
}
