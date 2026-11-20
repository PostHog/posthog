import api, { ApiConfig } from 'lib/api'
import { NetworkError, isBrowserNetworkFailure } from 'lib/api-error'

import {
    aiObservabilityTracesExportsCreate,
    aiObservabilityTracesExportsRetrieve,
    getAiObservabilityTracesExportsContentRetrieveUrl,
} from '../../generated/api'
import {
    AiObservabilityTracesExportsContentRetrievePurpose,
    ExportStatusEnumApi,
    type TraceExportApi,
} from '../../generated/api.schemas'
import { encodeTraceIdSegment } from './traceIdSegment'

export const COPY_TRACE_MAX_MEGABYTES = 5
const COPY_TRACE_MAX_BYTES = COPY_TRACE_MAX_MEGABYTES * 1_000_000
const FIRST_POLL_DELAY_MS = 500
const MAX_POLL_DELAY_MS = 3000
const NETWORK_RETRY_DELAY_MS = 1000
const CLIPBOARD_TEXT_TYPE = 'text/plain'

export class TraceExportFailedError extends Error {}

/**
 * A request that did not complete because the connection failed, not because of a fault in our code.
 * The API client turns a rejected `fetch` into a `NetworkError`. A body stream that fails part way
 * through is read here and not by the API client, so it keeps the raw browser error, such as WebKit's "Load failed".
 */
export function isNetworkFailure(error: unknown): boolean {
    return error instanceof NetworkError || isBrowserNetworkFailure(error)
}

export class TraceTooLargeToCopyError extends Error {
    constructor(readonly traceExport: TraceExportApi) {
        super(`The trace is larger than ${COPY_TRACE_MAX_MEGABYTES} MB.`)
    }
}

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

async function readCapped(
    response: Response,
    traceExport: TraceExportApi,
    stopReading: () => void
): Promise<TraceExportText> {
    if (!response.body) {
        throw new Error('The export came back empty.')
    }
    const reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let sizeBytes = 0
    for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
        sizeBytes += chunk.value.byteLength
        if (sizeBytes > COPY_TRACE_MAX_BYTES) {
            // Abort the request rather than cancel the reader: the API client keeps a clone of the response,
            // and a cancel waits until every clone of the body is cancelled too.
            stopReading()
            throw new TraceTooLargeToCopyError(traceExport)
        }
        chunks.push(chunk.value)
    }
    const decoder = new TextDecoder()
    const text = chunks.map((chunk) => decoder.decode(chunk, { stream: true })).join('') + decoder.decode()
    return { text, sizeBytes }
}

/**
 * Writes a trace export and reads it back as text, giving up once it passes the copy cap.
 * After a network failure it starts again one time with a new export.
 *
 * Throws `TraceExportFailedError` when the export fails and `TraceTooLargeToCopyError` past the cap.
 */
export async function readTraceExportText(params: ReadTraceExportTextParams): Promise<TraceExportText> {
    try {
        return await readTraceExportTextOnce(params)
    } catch (error) {
        if (params.signal.aborted || !isNetworkFailure(error)) {
            throw error
        }
        await sleep(NETWORK_RETRY_DELAY_MS, params.signal)
        return await readTraceExportTextOnce(params)
    }
}

async function readTraceExportTextOnce({
    traceId,
    timestampHint,
    signal,
}: ReadTraceExportTextParams): Promise<TraceExportText> {
    const projectId = String(ApiConfig.getCurrentProjectId())
    const segment = encodeTraceIdSegment(traceId)
    const created = await aiObservabilityTracesExportsCreate(
        projectId,
        segment,
        timestampHint ? { timestamp_hint: timestampHint } : {},
        { signal }
    )
    const traceExport = await waitForExport(projectId, segment, created, signal)
    if (traceExport.status === ExportStatusEnumApi.Failed) {
        throw new TraceExportFailedError(traceExport.exception ?? "Couldn't export this trace. Try again.")
    }
    const read = new AbortController()
    const stopReading = (): void => read.abort(signal.reason)
    signal.addEventListener('abort', stopReading, { once: true })
    try {
        // nosemgrep: prefer-codegen-api -- an export download; the generated client parses JSON, and the cap needs the raw body stream
        const response = await api.getResponse(
            getAiObservabilityTracesExportsContentRetrieveUrl(projectId, segment, traceExport.id, {
                purpose: AiObservabilityTracesExportsContentRetrievePurpose.Copy,
            }),
            { signal: read.signal }
        )
        return await readCapped(response, traceExport, () => read.abort())
    } finally {
        signal.removeEventListener('abort', stopReading)
    }
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
