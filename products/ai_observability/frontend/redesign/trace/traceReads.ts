import { aiObservabilityTracesNodesRetrieve, aiObservabilityTracesRetrieve } from '../../generated/api'
import type { TraceApi, TraceNodeDetailApi } from '../../generated/api.schemas'
import { encodeTraceIdSegment } from './traceIdSegment'

function hintParams(timestampHint: string | null): { timestamp_hint: string } | undefined {
    return timestampHint ? { timestamp_hint: timestampHint } : undefined
}

export function readTrace(projectId: string, traceId: string, timestampHint: string | null): Promise<TraceApi> {
    return aiObservabilityTracesRetrieve(projectId, encodeTraceIdSegment(traceId), hintParams(timestampHint))
}

export function readTraceNode(
    projectId: string,
    traceId: string,
    nodeId: string,
    timestampHint: string | null
): Promise<TraceNodeDetailApi> {
    return aiObservabilityTracesNodesRetrieve(
        projectId,
        encodeTraceIdSegment(traceId),
        encodeTraceIdSegment(nodeId),
        hintParams(timestampHint)
    )
}
