import type { TraceNodeEventApi, TraceNodeKindEnumApi, TraceNodeStatsApi } from '../../../generated/api.schemas'
import { NodeDetailProps } from '../components/NodeDetail'
import { TraceViewReadyProps } from '../components/TraceView'
import { RawLoad } from '../types'

export type SampleNodeDetail = Omit<
    NodeDetailProps,
    'node' | 'tab' | 'onTabChange' | 'onViewInThread' | 'messagesOpening' | 'onMessagesOpeningChange' | 'onSelectNode'
>

export type SampleTraceFixture = Pick<TraceViewReadyProps, 'header' | 'summary' | 'tree' | 'thread' | 'timeline'> & {
    initialNodeId: string
    details: Record<string, SampleNodeDetail>
}

export function sampleRaw(
    kind: TraceNodeKindEnumApi,
    id: string,
    event: Pick<TraceNodeEventApi, 'name' | 'timestamp' | 'properties'> | null
): RawLoad {
    return {
        status: 'ready',
        raw: {
            id,
            kind,
            event: event && { ...event, uuid: id, ioKeys: { input: null, output: null, tools: null } },
        },
    }
}

export function sampleStats(stats: Partial<TraceNodeStatsApi>): TraceNodeStatsApi {
    return {
        costUsd: null,
        inputTokens: null,
        outputTokens: null,
        cacheReadTokens: null,
        cacheWriteTokens: null,
        latencyMs: null,
        ...stats,
    }
}
