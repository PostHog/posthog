import { ApiConfig } from 'lib/api'

import {
    aiObservabilityTracesExportsContentRetrieve,
    aiObservabilityTracesExportsCreate,
    aiObservabilityTracesExportsRetrieve,
} from '../../generated/api'
import { ExportStatusEnumApi, TraceExportPurposeEnumApi, type TraceExportApi } from '../../generated/api.schemas'
import { encodeTraceIdSegment } from './traceIdSegment'

const FIRST_POLL_DELAY_MS = 500
const MAX_POLL_DELAY_MS = 3000
const CLIPBOARD_TEXT_TYPE = 'text/plain'

export class TraceExportFailedError extends Error {}

/** The server refuses a copy export past its size cap, and the message says so. */
export class TraceTooLargeToCopyError extends Error {}

export interface TraceExportText {
    text: string
    sizeBytes: number
}

export interface ReadTraceExportTextParams {
    traceId: string
    timestampHint: string | null
    signal: AbortSignal
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const timeout = window.setTimeout(resolve, ms)
        signal.addEventListener(
            'abort',
            () => {
                window.clearTimeout(timeout)
                reject(signal.reason)
            },
            { once: true }
        )
    })
}

async function waitForExport(
    projectId: string,
    segment: string,
    traceExport: TraceExportApi,
    signal: AbortSignal
): Promise<TraceExportApi> {
    let delay = FIRST_POLL_DELAY_MS
    while (traceExport.status === ExportStatusEnumApi.Pending) {
        await sleep(delay, signal)
        delay = Math.min(delay * 1.5, MAX_POLL_DELAY_MS)
        traceExport = await aiObservabilityTracesExportsRetrieve(projectId, segment, traceExport.id, { signal })
    }
    return traceExport
}

/**
 * Writes a copy export of the trace and reads it back as text.
 *
 * Throws `TraceTooLargeToCopyError` when the trace is over the server's copy cap, and `TraceExportFailedError` when
 * the export fails for another reason.
 */
export async function readTraceExportText({
    traceId,
    timestampHint,
    signal,
}: ReadTraceExportTextParams): Promise<TraceExportText> {
    const projectId = String(ApiConfig.getCurrentProjectId())
    const segment = encodeTraceIdSegment(traceId)
    const created = await aiObservabilityTracesExportsCreate(
        projectId,
        segment,
        {
            purpose: TraceExportPurposeEnumApi.Copy,
            ...(timestampHint ? { timestamp_hint: timestampHint } : {}),
        },
        { signal }
    )
    const traceExport = await waitForExport(projectId, segment, created, signal)
    if (traceExport.status === ExportStatusEnumApi.Failed) {
        const message = traceExport.exception ?? "Couldn't export this trace. Try again."
        throw traceExport.tooLarge ? new TraceTooLargeToCopyError(message) : new TraceExportFailedError(message)
    }
    const file = await aiObservabilityTracesExportsContentRetrieve(projectId, segment, traceExport.id, { signal })
    const text = JSON.stringify(file)
    return { text, sizeBytes: new TextEncoder().encode(text).byteLength }
}

/**
 * Puts text that is still loading on the clipboard. Resolves to false when the browser refused.
 *
 * Call it in the same task as the click: Safari and Firefox only accept a clipboard write that starts
 * inside the user gesture, so the pending text goes onto the `ClipboardItem` instead of being awaited first.
 */
export async function writePendingTextToClipboard(text: Promise<string>): Promise<boolean> {
    // Chrome accepts only a Blob promise on a ClipboardItem, not a string promise.
    const blob = text.then((value) => new Blob([value], { type: CLIPBOARD_TEXT_TYPE }))
    // The caller handles a failed read. Nothing else observes this promise when the browser cannot write it.
    blob.catch(() => {})
    if (typeof ClipboardItem === 'undefined' || !navigator.clipboard?.write) {
        return false
    }
    try {
        await navigator.clipboard.write([new ClipboardItem({ [CLIPBOARD_TEXT_TYPE]: blob })])
        return true
    } catch {
        return false
    }
}
