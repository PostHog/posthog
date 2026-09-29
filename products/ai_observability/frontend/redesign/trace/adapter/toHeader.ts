import { urls } from 'scenes/urls'

import { LLMTrace } from '~/queries/schema/schema-general'

import { TraceHeaderProps } from '../components/TraceHeader'
import { hasTraceError } from './toTraceTree'

export interface TraceNeighbours {
    olderTraceId: string | null
    olderTimestamp: string | null
    newerTraceId: string | null
    newerTimestamp: string | null
}

function traceHref(traceId: string | null, timestamp: string | null): string | null {
    return traceId ? urls.aiObservabilityTrace(traceId, { timestamp: timestamp ?? undefined }) : null
}

export function toHeader(trace: LLMTrace, neighbours: TraceNeighbours): TraceHeaderProps {
    return {
        name: trace.traceName || 'Untitled trace',
        hasError: hasTraceError(trace),
        olderHref: traceHref(neighbours.olderTraceId, neighbours.olderTimestamp),
        newerHref: traceHref(neighbours.newerTraceId, neighbours.newerTimestamp),
        backHref: urls.aiObservabilityTraces(),
    }
}
