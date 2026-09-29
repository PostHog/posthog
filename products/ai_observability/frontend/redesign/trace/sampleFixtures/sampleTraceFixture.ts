import { NodeDetailProps } from '../components/NodeDetail'
import { TraceViewReadyProps } from '../components/TraceView'
import { NodeStats } from '../types'

export type SampleNodeDetail = Omit<NodeDetailProps, 'node' | 'tab' | 'onTabChange' | 'onViewInThread'>

export type SampleTraceFixture = Pick<TraceViewReadyProps, 'header' | 'summary' | 'tree' | 'thread' | 'timeline'> & {
    initialNodeId: string
    details: Record<string, SampleNodeDetail>
}

export function sampleStats(stats: Partial<NodeStats>): NodeStats {
    return {
        costUsd: null,
        inputTokens: null,
        outputTokens: null,
        cacheReadTokens: null,
        latencyMs: null,
        ...stats,
    }
}
