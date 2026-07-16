// posthog-js autocaptures uncaught errors and unhandled rejections into `$exception`
// events, serializing each error in the cause chain into `$exception_list` (one entry
// per error, each with a `type` and `value`). These are pure `before_send` filters that
// drop whole `$exception` events that are benign noise, so they never reach error
// tracking. They are installed centrally at posthog init (see `loadPostHogJS`) so they
// apply regardless of which code path threw.

type MinimalEvent = { event?: string; properties?: Record<string, any> } | null

type ExceptionListEntry = { type?: string; value?: string }

function exceptionList(event: NonNullable<MinimalEvent>): ExceptionListEntry[] {
    return (event.properties?.$exception_list ?? []) as ExceptionListEntry[]
}

// Drops query-cancellation noise. When a viewer starts a new search (logs, tracing, ...)
// the in-flight request is aborted with `AbortController.abort(new DOMException(msg,
// 'AbortError'))`. That is not a failure, but posthog-js's global unhandledrejection
// autocapture still turns it into an `$exception` event. The `onFailure` guard in
// `initKea` already skips the kea-loaders path via `error.name === 'AbortError'`; this
// catches the residual events that reach error tracking through autocapture instead.
// A plain Error with `name = 'AbortError'` serializes to `type = 'AbortError'`; a
// DOMException serializes to `type = 'DOMException'`, `value = 'AbortError: <message>'`
// (see posthog-js's DOMExceptionCoercer) — so we match either shape.
export function dropAbortErrors<T extends MinimalEvent>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const isAbort = exceptionList(event).some(
        (ex) => ex?.type === 'AbortError' || (typeof ex?.value === 'string' && /^AbortError\b/.test(ex.value))
    )
    return isAbort ? null : event
}

// Filters `$exception` events whose chain contains a ReadOnlyModeError so the self
// read-only feature doesn't spam error tracking for blocks-by-design. The chain walk
// catches wrapped errors (e.g. `new Error('...', { cause: e })`).
export function dropReadOnlyExceptions<T extends MinimalEvent>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    if (exceptionList(event).some((ex) => ex?.type === 'ReadOnlyModeError')) {
        return null
    }
    return event
}
