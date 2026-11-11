import { dayjs } from 'lib/dayjs'

import type { TraceListRow } from '../redesign/trace/traceListRows'
import type { TraceWithSummary } from './clusterDetailLogic'
import type { ClusteringLevel } from './types'

export function toClusterTraceDrawerRow(
    { traceId, traceInfo, summary }: TraceWithSummary,
    clusteringLevel: ClusteringLevel
): TraceListRow | null {
    if (clusteringLevel === 'evaluation') {
        // `traceInfo.trace_id` is the evaluation's own uuid when its metadata could not be resolved.
        return summary?.traceId
            ? { traceId: summary.traceId, timestamp: null, stepId: summary.generationId ?? null }
            : null
    }
    const timestamp = traceInfo.timestamp ? dayjs.utc(traceInfo.timestamp).toISOString() : null
    if (clusteringLevel === 'generation') {
        return { traceId: traceInfo.trace_id, timestamp, stepId: traceInfo.generation_id ?? null }
    }
    return { traceId, timestamp, stepId: null }
}
