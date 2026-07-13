import { BeforeSendFn, CaptureResult } from 'posthog-js'

/*
posthog-js exposes a single `before_send` config slot, but several independent concerns need to
filter outgoing events before they leave the browser (cancellation noise, read-only mode, the
exporter's token redaction). This registry composes them so each can add or remove its own filter
without clobbering the others. Filters run in registration order; the first to return null drops
the event.
*/
const filters = new Set<BeforeSendFn>()

/** Register a `before_send` filter. Returns a function that unregisters it. */
export function registerBeforeSendFilter(filter: BeforeSendFn): () => void {
    filters.add(filter)
    return () => {
        filters.delete(filter)
    }
}

/*
Drops `$exception` events that are cooperative fetch cancellations. When we abort an in-flight
query (a superseded query, an unmount, a manual cancel) the browser rejects the fetch with a
`DOMException` named `AbortError` — including the bare `abort()` calls that reject with the literal
"signal is aborted without reason". These are expected control flow, not bugs. The loaders
`onFailure` in `initKea.ts` already swallows the ones that flow through kea, but aborts that surface
via the unhandled-rejection path (auto-captured by posthog-js) bypass that filter, so we drop them
centrally here too. `AbortError` is only produced by deliberate aborts, so this never hides a real
fetch failure (those reject with `TypeError` and friends).
*/
export const dropCancellationExceptions: BeforeSendFn = (event) => {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string; value?: string }>
    if (list.some(isAbortException)) {
        return null
    }
    return event
}

// posthog-js records an exception's `type` from the error's `name`, so an aborted fetch's
// `DOMException` surfaces as `AbortError`. The value fallback covers the case where it's instead
// labeled `DOMException` (its constructor name), matched narrowly to the known abort messages so
// unrelated DOMExceptions (QuotaExceededError, SecurityError, ...) are never dropped.
function isAbortException(ex: { type?: string; value?: string }): boolean {
    return (
        ex?.type === 'AbortError' ||
        (ex?.type === 'DOMException' &&
            typeof ex.value === 'string' &&
            (ex.value.includes('signal is aborted') || ex.value === 'new query started'))
    )
}

/** The single `before_send` handed to posthog-js. Runs the built-in cancellation filter, then any
 * dynamically registered filters. */
export const composedBeforeSend: BeforeSendFn = (event) => {
    let result: CaptureResult | null = dropCancellationExceptions(event)
    for (const filter of filters) {
        if (result === null) {
            break
        }
        result = filter(result)
    }
    return result
}
