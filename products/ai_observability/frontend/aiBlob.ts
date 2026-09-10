import posthog from 'posthog-js'

/** Frontend twin of the ingestion pointer module: the only place phaiblob:// URIs are interpreted. */
export interface AiBlobPointer {
    version: string
    algo: string
    hash: string
    mime: string | null
    size: number | null
}

const POINTER_SCHEME = 'phaiblob://'
const POINTER_RE = /^phaiblob:\/\/(v1)\/(sha256)\/([0-9a-f]{64})(?:\?(.*))?$/
// TODO: replace the whole URL rather than its data component, so a valid data URL can't be clobbered.
const DATA_URI_WRAPPED_POINTER = /^data:[\w.+-]+\/[\w.+-]+;base64,(phaiblob:\/\/.*)$/

export function parseAiBlobPointer(value: string): AiBlobPointer | null {
    const unwrapped = DATA_URI_WRAPPED_POINTER.exec(value)?.[1] ?? value
    if (!unwrapped.startsWith(POINTER_SCHEME)) {
        return null
    }
    const match = POINTER_RE.exec(unwrapped)
    if (!match) {
        return null
    }
    const params = new URLSearchParams(match[4] ?? '')
    const sizeRaw = params.get('size')
    return {
        version: match[1],
        algo: match[2],
        hash: match[3],
        mime: params.get('mime'),
        size: sizeRaw && /^\d+$/.test(sizeRaw) ? parseInt(sizeRaw, 10) : null,
    }
}

export function resolveAiBlobUrl(value: string, teamId: number | string | null): string {
    const pointer = parseAiBlobPointer(value)
    if (!pointer || teamId === null || teamId === undefined || teamId === '') {
        return value
    }
    return `/api/projects/${teamId}/ai_blob/${pointer.version}/${pointer.algo}/${pointer.hash}`
}

/**
 * Resolves a raw `data` field (base64 payload or, post-offload, a phaiblob:// pointer) to a
 * renderable src: the blob endpoint URL if it's a pointer, otherwise the `data:` URI it always was.
 */
export function resolveDataUri(rawData: string, mimeType: string, teamId: number | string | null): string {
    const resolved = resolveAiBlobUrl(rawData, teamId)
    return resolved !== rawData ? resolved : `data:${mimeType};base64,${rawData}`
}

const BLOB_ENDPOINT_RE = /\/ai_blob\/v1\/sha256\/[0-9a-f]{64}$/

const reportedRenders = new Map<string, true>()
const MAX_REPORTED_RENDERS = 1000

type TimingWaiter = (timing?: PerformanceResourceTiming) => void

const blobTimings = new Map<string, PerformanceResourceTiming>()
const MAX_TRACKED_TIMINGS = 200
const waitersByUrl = new Map<string, Set<TimingWaiter>>()
const TIMING_WAIT_MS = 1000

function isResourceTiming(entry: PerformanceEntry): entry is PerformanceResourceTiming {
    return entry.entryType === 'resource'
}

function forgetWaiter(url: string, waiter: TimingWaiter): void {
    const waiting = waitersByUrl.get(url)
    if (!waiting) {
        return
    }
    waiting.delete(waiter)
    if (waiting.size === 0) {
        waitersByUrl.delete(url)
    }
}

function rememberBlobTiming(entry: PerformanceResourceTiming): void {
    if (!BLOB_ENDPOINT_RE.test(entry.name)) {
        return
    }
    if (!blobTimings.has(entry.name) && blobTimings.size >= MAX_TRACKED_TIMINGS) {
        const oldestUrl = blobTimings.keys().next().value
        if (oldestUrl !== undefined) {
            blobTimings.delete(oldestUrl)
        }
    }
    blobTimings.set(entry.name, entry)
    const waiting = waitersByUrl.get(entry.name)
    if (waiting) {
        waitersByUrl.delete(entry.name)
        waiting.forEach((waiter) => waiter(entry))
    }
}

/**
 * The browser keeps only 250 resource entries, and the app fills that buffer long before anyone opens a
 * trace, so performance.getEntriesByName() finds nothing for a blob that just rendered. An observer
 * receives every entry from registration onward, which does not depend on the buffer.
 */
function observeBlobTimings(): void {
    if (typeof PerformanceObserver === 'undefined') {
        return
    }
    try {
        new PerformanceObserver((list) => {
            list.getEntries().filter(isResourceTiming).forEach(rememberBlobTiming)
        }).observe({ type: 'resource', buffered: true })
    } catch {
        // A browser that does not report resource entries leaves the timing properties null.
    }
}

observeBlobTimings()

/**
 * Resource entries reach the observer on a queued task, so a load handler can run before the entry for
 * its own request lands. Waiting closes that gap. The timeout keeps a render whose entry never arrives
 * reporting null timing instead of never reporting at all.
 */
function awaitBlobTiming(url: string): Promise<PerformanceResourceTiming | undefined> {
    const known = blobTimings.get(url)
    blobTimings.delete(url)
    if (known || typeof PerformanceObserver === 'undefined') {
        return Promise.resolve(known)
    }
    return new Promise((resolve) => {
        const waiter = (timing?: PerformanceResourceTiming): void => {
            clearTimeout(timeout)
            forgetWaiter(url, waiter)
            resolve(timing)
        }
        const timeout = setTimeout(waiter, TIMING_WAIT_MS)
        const waiting = waitersByUrl.get(url)
        if (waiting) {
            waiting.add(waiter)
        } else {
            waitersByUrl.set(url, new Set([waiter]))
        }
    })
}

async function captureBlobRender(
    src: string,
    mediaKind: 'image' | 'audio',
    outcome: 'success' | 'error'
): Promise<void> {
    const key = `${outcome}:${src}`
    if (reportedRenders.has(key)) {
        return
    }
    if (reportedRenders.size >= MAX_REPORTED_RENDERS) {
        const oldestKey = reportedRenders.keys().next().value
        if (oldestKey !== undefined) {
            reportedRenders.delete(oldestKey)
        }
    }
    reportedRenders.set(key, true)
    const timing = await awaitBlobTiming(new URL(src, window.location.origin).toString())
    posthog.capture('llma ai blob render', {
        outcome,
        media_kind: mediaKind,
        transfer_size_bytes: timing ? timing.transferSize : null,
        decoded_body_bytes: timing ? timing.decodedBodySize : null,
        from_browser_cache: timing ? timing.transferSize === 0 && timing.decodedBodySize > 0 : null,
    })
}

export function aiBlobRenderHandlers(
    src: string,
    mediaKind: 'image' | 'audio'
): { onLoad?: () => void; onCanPlay?: () => void; onError?: () => void } {
    if (!BLOB_ENDPOINT_RE.test(src)) {
        return {}
    }
    const report = (outcome: 'success' | 'error') => (): void => {
        void captureBlobRender(src, mediaKind, outcome)
    }
    return {
        ...(mediaKind === 'image' ? { onLoad: report('success') } : { onCanPlay: report('success') }),
        onError: report('error'),
    }
}
