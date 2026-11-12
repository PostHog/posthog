import { ReactNode } from 'react'

import { TZLabel } from 'lib/components/TZLabel'

import type { TraceApi, TraceNodeApi, TraceNodeDetailApi } from '../../../generated/api.schemas'
import { formatCacheTokens, formatCostUsd, formatLatencyMs, formatTokenCounts } from './formatStats'

const UNKNOWN_VALUE = <span className="text-secondary">Unknown</span>

type PropertyRow = [label: string, value: ReactNode]

export interface NodePropertyListProps {
    node: TraceNodeApi
    /** The step's read, null while it loads. The root's properties come from the trace. */
    detail: TraceNodeDetailApi | null
    trace: Pick<TraceApi, 'createdAt' | 'sessionId' | 'person'>
}

interface ShownProperties {
    timestamp: string | null
    provider: string | null
    temperature: number | null
    sessionId: string | null
    promptName: string | null
    promptVersion: number | null
}

function shownProperties(
    node: TraceNodeApi,
    detail: TraceNodeDetailApi | null,
    trace: NodePropertyListProps['trace']
): ShownProperties {
    if (node.kind === 'trace') {
        return {
            timestamp: trace.createdAt,
            provider: null,
            temperature: null,
            sessionId: trace.sessionId,
            promptName: null,
            promptVersion: null,
        }
    }
    return {
        timestamp: detail?.event?.timestamp ?? null,
        provider: detail?.metadata.provider ?? null,
        temperature: detail?.metadata.temperature ?? null,
        sessionId: detail?.metadata.sessionId ?? null,
        promptName: detail?.metadata.promptName ?? null,
        promptVersion: detail?.metadata.promptVersion ?? null,
    }
}

export function NodePropertyList({ node, detail, trace }: NodePropertyListProps): JSX.Element {
    const { stats } = node
    const properties = shownProperties(node, detail, trace)
    const time = properties.timestamp ? (
        <TZLabel
            time={properties.timestamp}
            timestampStyle="absolute"
            formatDate="MMM D,"
            formatTime="HH:mm:ss"
            showSeconds
            className="font-mono"
        />
    ) : null
    const tokens = formatTokenCounts(stats.inputTokens, stats.outputTokens) ?? UNKNOWN_VALUE
    const cache = formatCacheTokens(stats.cacheReadTokens, stats.cacheWriteTokens)
    const latency = stats.latencyMs !== null ? formatLatencyMs(stats.latencyMs) : UNKNOWN_VALUE
    const cost = stats.costUsd !== null ? formatCostUsd(stats.costUsd) : UNKNOWN_VALUE
    const prompt =
        properties.promptName && properties.promptVersion !== null
            ? `${properties.promptName} v${properties.promptVersion}`
            : properties.promptName

    const rows: PropertyRow[] =
        node.kind === 'generation'
            ? [
                  ['Model', node.model],
                  ['Provider', properties.provider],
                  ['Temperature', properties.temperature !== null ? String(properties.temperature) : null],
                  ['Tokens', tokens],
                  ['Cache', cache],
                  ['Latency', latency],
                  ['Cost', cost],
                  ['Prompt', prompt],
                  ['Session', properties.sessionId],
                  ['Time', time],
              ]
            : [
                  ['Name', node.name],
                  ['Kind', node.kind],
                  ['Time', time],
                  ['Person', trace.person?.label ?? null],
                  ['Latency', latency],
                  ['Tokens', tokens],
                  ['Cache', cache],
                  ['Cost', cost],
                  ['Session', properties.sessionId],
              ]

    return (
        <dl className="m-0 grid grid-cols-[max-content_1fr] items-baseline gap-x-8 gap-y-2 text-sm">
            {rows
                .filter(([, value]) => value !== null)
                .map(([label, value]) => (
                    <div key={label} className="contents">
                        <dt className="text-secondary">{label}</dt>
                        <dd className="m-0 min-w-0 font-mono text-xs break-all">{value}</dd>
                    </div>
                ))}
        </dl>
    )
}
