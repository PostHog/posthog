import { IconPerson } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { BreakdownList } from '../../shared/components/BreakdownList'
import { ExampleItem, ExampleList } from '../../shared/components/ExampleList'
import { StatTiles } from '../../shared/components/StatTiles'
import { VolumeCell } from '../../shared/components/VolumeCell'
import { formatCostUsd, formatLatencyMs } from '../../trace/components/formatStats'
import { ShortTimestamp } from '../../trace/components/ShortTimestamp'
import type { PersonDetail as PersonDetailData, PersonTrace } from '../peopleQueries'
import { ErrorRateTag } from './ErrorRateTag'

export interface PersonDetailProps {
    /** Null while loading. */
    detail: PersonDetailData | null
    labels: string[]
    personHref: string
    activeTraceId: string | null
    onOpenTrace: (trace: PersonTrace) => void
    onFilterModel: (model: string) => void
    onFilterTool: (tool: string) => void
}

function toItem(trace: PersonTrace): ExampleItem {
    return {
        key: trace.traceId,
        title: trace.name ?? `Trace ${trace.traceId.slice(0, 8)}`,
        detail: `${humanFriendlyNumber(trace.generations)} ${trace.generations === 1 ? 'generation' : 'generations'} · ${formatCostUsd(trace.costUsd)}`,
        tags: [
            ...(trace.errors > 0
                ? [{ label: trace.errors === 1 ? '1 error' : `${trace.errors} errors`, type: 'danger' as const }]
                : []),
            ...trace.models.map((model) => ({ label: model, type: 'muted' as const })),
        ],
        timestamp: trace.timestamp,
        metric: trace.latency !== null ? formatLatencyMs(trace.latency * 1000) : null,
    }
}

export function PersonDetail({
    detail,
    labels,
    personHref,
    activeTraceId,
    onOpenTrace,
    onFilterModel,
    onFilterTool,
}: PersonDetailProps): JSX.Element {
    const summary = detail?.summary ?? null
    const value = <T,>(read: (row: NonNullable<typeof summary>) => T): T | string | null =>
        detail === null ? null : summary ? read(summary) : '-'
    const tracesById = new Map((detail?.traces ?? []).map((trace) => [trace.traceId, trace]))

    return (
        <div className="flex flex-col gap-4">
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPerson />}
                    to={personHref}
                    data-attr="ai-observability-person-drawer-profile"
                >
                    View person
                </LemonButton>
            </div>
            <StatTiles
                tiles={[
                    { label: 'Traces', value: value((row) => humanFriendlyNumber(row.traces)) },
                    { label: 'Generations', value: value((row) => humanFriendlyNumber(row.generations)) },
                    {
                        label: 'Errors',
                        value: value((row) => <ErrorRateTag errors={row.errors} total={row.generations} />),
                    },
                    { label: 'Cost', value: value((row) => formatCostUsd(row.costUsd)) },
                    {
                        label: 'p95 latency',
                        value: value((row) =>
                            row.p95LatencySeconds !== null ? formatLatencyMs(row.p95LatencySeconds * 1000) : '-'
                        ),
                    },
                    { label: 'Last seen', value: value((row) => <ShortTimestamp time={row.lastSeen} />) },
                ]}
            />
            {summary ? (
                <VolumeCell values={summary.volume} labels={labels} name="Generations" className="h-16 w-full" />
            ) : null}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <BreakdownList
                    title="Models"
                    rows={detail?.models ?? null}
                    emptyText="No model recorded on these generations."
                    onSelect={onFilterModel}
                    data-attr="ai-observability-person-drawer-model"
                />
                <BreakdownList
                    title="Tools"
                    rows={detail?.tools ?? null}
                    emptyText="No tool calls."
                    onSelect={onFilterTool}
                    data-attr="ai-observability-person-drawer-tool"
                />
            </div>
            <ExampleList
                title="Recent traces"
                examples={detail ? detail.traces.map(toItem) : null}
                activeKey={activeTraceId}
                emptyText="No traces in this date range."
                onOpen={(item) => {
                    const trace = tracesById.get(item.key)
                    if (trace) {
                        onOpenTrace(trace)
                    }
                }}
                data-attr="ai-observability-person-drawer-trace"
            />
        </div>
    )
}
