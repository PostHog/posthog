import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { CanvasCapabilities, assertCanvasCapability } from './canvasArtifactBridge'

// Mirror the desktop host's result bounds so a canvas built and tested there
// behaves the same in a notebook.
const MAX_CANVAS_RESULT_ROWS = 1_000
const MAX_CANVAS_RESULT_BYTES = 2 * 1024 * 1024

interface CanvasDataResult {
    columns: string[]
    results: unknown[]
}

function boundedResult(result: CanvasDataResult): CanvasDataResult {
    if (result.results.length > MAX_CANVAS_RESULT_ROWS || JSON.stringify(result).length > MAX_CANVAS_RESULT_BYTES) {
        throw new Error('Canvas data result exceeds the result limit')
    }
    return result
}

async function runCanvasQuery(payload: Record<string, unknown>): Promise<CanvasDataResult> {
    const typedQuery = payload.query
    const hogql = payload.hogql
    const isTyped = typedQuery != null && typeof typedQuery === 'object'
    if (!isTyped && (typeof hogql !== 'string' || !hogql)) {
        throw new Error('ph.query requires a typed query node or a HogQL string')
    }
    const node = isTyped
        ? (typedQuery as Record<string, any>)
        : { kind: 'HogQLQuery', query: hogql as string, tags: { productKey: 'notebooks' } }
    // The insights avenue: serve a fresh cached result if present, otherwise
    // compute it now - so the numbers match the PostHog UI.
    const response = await api.query(node, { refresh: 'blocking' })
    const results = Array.isArray(response.results) ? response.results : []
    return boundedResult({
        columns: Array.isArray(response.columns) ? response.columns.map(String) : [],
        // HogQL returns rows; normalize a bare scalar row to a 1-cell array.
        // Typed nodes return series objects - pass them through untouched.
        results: isTyped ? results : results.map((r: unknown) => (Array.isArray(r) ? r : [r])),
    })
}

async function loadCanvasInsight(payload: Record<string, unknown>): Promise<CanvasDataResult> {
    const shortId = payload.shortId
    if (typeof shortId !== 'string' || !shortId) {
        throw new Error('ph.loadInsight(shortId) requires an insight short id')
    }
    const dateRange = (payload.dateRange ?? null) as { date_from?: string | null; date_to?: string | null } | null
    const response = await api.insights.loadInsight(shortId as any, undefined, 'blocking', dateRange)
    const insight = response.results?.[0]
    if (!insight) {
        throw new Error(`Insight "${shortId}" not found`)
    }
    const results = Array.isArray(insight.result) ? insight.result : []
    const isRows = (insight.query as Record<string, unknown> | null)?.kind === 'HogQLQuery'
    // The stored SQL result carries its column names, but InsightModel doesn't type them.
    const columns = (insight as Record<string, unknown>).columns
    return boundedResult({
        columns: Array.isArray(columns) ? columns.map(String) : [],
        results: isRows ? results.map((r: unknown) => (Array.isArray(r) ? r : [r])) : results,
    })
}

async function captureCanvasEvent(payload: Record<string, unknown>): Promise<{ ok: boolean }> {
    const event = payload.event
    if (typeof event !== 'string' || !event) {
        throw new Error('ph.capture(event) requires an event name')
    }
    // Capture goes to the CURRENT project with its public key - not the app's
    // own posthog-js instance, which reports to PostHog's project.
    const apiToken = teamLogic.findMounted()?.values.currentTeam?.api_token
    if (!apiToken) {
        throw new Error('No project capture key available')
    }
    const distinctId =
        (typeof payload.distinctId === 'string' && payload.distinctId) ||
        userLogic.findMounted()?.values.user?.distinct_id ||
        'notebook-canvas'
    const properties = (typeof payload.properties === 'object' && payload.properties) || {}
    const response = await fetch(`${window.location.origin}/i/v0/e/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            api_key: apiToken,
            event,
            distinct_id: distinctId,
            properties: { ...properties, $lib: 'posthog-canvas' },
        }),
    })
    if (!response.ok) {
        throw new Error(`Capture failed (${response.status})`)
    }
    return { ok: true }
}

/**
 * The host-side data avenue behind a canvas's `ph.*` shim, gated by the build
 * manifest's frozen capabilities. Runs against the signed-in session; no
 * credential ever crosses into the iframe.
 */
export async function handleCanvasDataRequest(
    method: string,
    payload: unknown,
    capabilities: CanvasCapabilities | undefined
): Promise<unknown> {
    assertCanvasCapability(capabilities, method, payload)
    const payloadRecord = (typeof payload === 'object' && payload !== null ? payload : {}) as Record<string, unknown>
    switch (method) {
        case 'query':
            return await runCanvasQuery(payloadRecord)
        case 'loadInsight':
            return await loadCanvasInsight(payloadRecord)
        case 'capture':
            return await captureCanvasEvent(payloadRecord)
        default:
            throw new Error(`Unknown data method "${method}"`)
    }
}
