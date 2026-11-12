import type { DatasetItemCreateApi, TraceNodeDatasetItemApi } from '../generated/api.schemas'

export interface TraceStep {
    traceId: string
    nodeId: string
    timestamp: string
}

export type DatasetItemDraft = Omit<DatasetItemCreateApi, 'dataset'>

export function isSameTraceStep(a: TraceStep, b: TraceStep): boolean {
    return a.traceId === b.traceId && a.nodeId === b.nodeId && a.timestamp === b.timestamp
}

export function toDatasetItemDraft(item: TraceNodeDatasetItemApi): DatasetItemDraft {
    return {
        client_item_id: item.clientItemId,
        source_trace_id: item.sourceTraceId,
        source_event_id: item.sourceEventId,
        source_timestamp: item.sourceTimestamp,
        input: item.input,
        source_output: item.sourceOutput,
        metadata: item.metadata,
    }
}
