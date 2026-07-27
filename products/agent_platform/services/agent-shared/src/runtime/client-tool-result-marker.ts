/**
 * Marker for buffered interactive client-tool results. Ingress's `/send`
 * (client_tool_result variant) appends `<PREFIX>:<json>` into
 * pending_inputs; the runner's resume scanner parses it and synthesises
 * a wake message. Mirrors `approval-marker.ts`.
 */

export const CLIENT_TOOL_RESULT_MARKER_PREFIX = '__POSTHOG_CLIENT_TOOL_RESULT__'

export type ClientToolResultPayload =
    | { call_id: string; result: Record<string, unknown> }
    | { call_id: string; error: string }

export function buildClientToolResultMarker(payload: ClientToolResultPayload): string {
    return `${CLIENT_TOOL_RESULT_MARKER_PREFIX}:${JSON.stringify(payload)}`
}

export function parseClientToolResultMarker(text: string): ClientToolResultPayload | null {
    if (!text.startsWith(`${CLIENT_TOOL_RESULT_MARKER_PREFIX}:`)) {
        return null
    }
    const raw = text.slice(CLIENT_TOOL_RESULT_MARKER_PREFIX.length + 1)
    let parsed: unknown
    try {
        parsed = JSON.parse(raw)
    } catch {
        return null
    }
    if (!parsed || typeof parsed !== 'object') {
        return null
    }
    const p = parsed as Record<string, unknown>
    if (typeof p.call_id !== 'string' || p.call_id.length === 0) {
        return null
    }
    if ('error' in p && typeof p.error === 'string') {
        return { call_id: p.call_id, error: p.error }
    }
    if ('result' in p && p.result && typeof p.result === 'object') {
        return { call_id: p.call_id, result: p.result as Record<string, unknown> }
    }
    return null
}
