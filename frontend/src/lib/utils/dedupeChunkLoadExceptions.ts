import { type BeforeSendFn, type CaptureResult } from 'posthog-js'

import { isChunkLoadError } from './isChunkLoadError'

interface ExceptionListItem {
    type?: string
    value?: string
}

// A single chunk-load failure is caught and captured by every nested ErrorBoundary it rethrows
// through on the way to the ChunkLoadErrorBoundary (see layout/ErrorBoundary). Those captures all
// fire synchronously during one React error-propagation pass, so one stale-deploy failure turns
// into N identical `$exception` events. Keep the first and drop the synchronous repeats.
//
// Distinct failures (a different chunk, so a different message) and non-chunk exceptions are never
// touched — only exact repeats of the same chunk error within the current task are dropped.
export function dedupeChunkLoadExceptions(): BeforeSendFn {
    const seenThisTask = new Set<string>()

    return (event: CaptureResult | null): CaptureResult | null => {
        if (!event || event.event !== '$exception') {
            return event
        }

        const list = event.properties?.$exception_list as ExceptionListItem[] | undefined
        const chunkError = Array.isArray(list)
            ? list.find((item) => isChunkLoadError({ name: item?.type, message: item?.value }))
            : undefined
        if (!chunkError) {
            return event
        }

        const key = `${chunkError.type ?? ''}:${chunkError.value ?? ''}`
        if (seenThisTask.has(key)) {
            return null
        }
        seenThisTask.add(key)
        // Clear once the synchronous burst settles so a genuinely new failure later still reports.
        setTimeout(() => seenThisTask.delete(key), 0)
        return event
    }
}
