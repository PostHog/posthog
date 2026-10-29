// Canonical trace URLs (JON-33). The URL is the atomic, shareable form of a trace view:
// `/tracing?trace=<hex>` opens the drawer, `&span=<hex>` anchors a span, and the optional `&ts=<iso>`
// carries the root timestamp so a cold load can bound the ClickHouse lookup to a narrow window. A link
// without `ts` still opens the trace: the backend finds it by id through the trace_id projection.

import { urls } from 'scenes/urls'

import { usableId } from './usableId'

export interface TraceLinkParams {
    traceId: string
    spanId?: string | null
    /** ISO timestamp of (any span of) the trace, used to bound the cold-load query. */
    ts?: string | null
}

// The trace API returns hex ids in uppercase, and the viewer matches the URL ids against them exactly.
// Other ids, such as the drawer's `ai:<uuid>` rows, keep their case.
export function inApiCase(id: string): string {
    return usableId(id) ? id.toUpperCase() : id
}

/** Path + query for a trace view, relative to the app root. */
export function traceUrl({ traceId, spanId, ts }: TraceLinkParams): string {
    const params = new URLSearchParams({ trace: inApiCase(traceId) })
    if (spanId) {
        params.set('span', inApiCase(spanId))
    }
    if (ts) {
        params.set('ts', ts)
    }
    return `${urls.tracing()}?${params.toString()}`
}
