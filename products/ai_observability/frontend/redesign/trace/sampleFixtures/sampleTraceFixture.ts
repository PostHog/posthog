import type { TraceNodeStatsApi } from '../../../generated/api.schemas'
import { NodeDetailProps } from '../components/NodeDetail'
import { TraceViewReadyProps } from '../components/TraceView'

export type SampleNodeDetail = Omit<NodeDetailProps, 'node' | 'tab' | 'onTabChange' | 'onViewInThread' | 'onSelectNode'>

export type SampleTraceFixture = Pick<TraceViewReadyProps, 'header' | 'summary' | 'tree' | 'thread' | 'timeline'> & {
    initialNodeId: string
    details: Record<string, SampleNodeDetail>
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
