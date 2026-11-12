import type {
    TraceEvaluationResultApi,
    TraceNodeContentApi,
    TraceNodeEventApi,
    TraceNodeKindEnumApi,
    TraceNodeMetadataApi,
    TraceNodeStatsApi,
} from '../../../generated/api.schemas'
import { NodeDetailProps } from '../components/NodeDetail'
import { TraceSummaryBarProps } from '../components/TraceSummaryBar'
import { TraceViewReadyProps } from '../components/TraceView'
import { RawLoad } from '../types'

type ReadyRaw = Extract<RawLoad, { status: 'ready' }>

export type SampleNodeDetail = Pick<NodeDetailProps, 'load' | 'raw'>

export type SampleTraceFixture = Pick<TraceViewReadyProps, 'header' | 'tree' | 'thread' | 'timeline'> & {
    trace: TraceSummaryBarProps['trace'] & NodeDetailProps['trace']
    initialNodeId: string
    details: Record<string, SampleNodeDetail>
    evaluationResults: TraceEvaluationResultApi[]
}

export function sampleRaw(
    kind: TraceNodeKindEnumApi,
    id: string,
    event: Pick<TraceNodeEventApi, 'name' | 'timestamp' | 'properties'> | null
): ReadyRaw {
    return {
        status: 'ready',
        raw: {
            id,
            kind,
            event: event && { ...event, uuid: id, ioKeys: { input: null, output: null, tools: null } },
        },
    }
}

const NO_METADATA: TraceNodeMetadataApi = {
    provider: null,
    temperature: null,
    sessionId: null,
    promptName: null,
    promptVersion: null,
}

/** A step read as the node resource returns it, with its id, kind and event taken from the raw read. */
export function sampleDetail({
    raw,
    content,
    error = null,
    metadata = {},
}: {
    raw: ReadyRaw
    content: TraceNodeContentApi
    error?: string | null
    metadata?: Partial<TraceNodeMetadataApi>
}): SampleNodeDetail {
    const { id, kind, event } = raw.raw
    return {
        load: {
            status: 'ready',
            node: {
                id,
                kind,
                error,
                metadata: { ...NO_METADATA, ...metadata },
                event: event && { name: event.name, uuid: event.uuid, timestamp: event.timestamp },
                content,
            },
        },
        raw,
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
