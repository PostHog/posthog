import { BeforeSendFn } from 'posthog-js'

// A minimal shape of the posthog-js event passed to `before_send`, kept loose so the
// filters are trivially unit-testable without constructing a full `CaptureResult`.
type FilterableEvent = { event?: string; properties?: Record<string, any> } | null

// Drops `$exception` events whose chain contains a ReadOnlyModeError so the read-only
// feature doesn't spam error tracking for blocks-by-design. The chain walk catches
// wrapped errors (e.g. `new Error('...', { cause: e })`) because posthog-js appends the
// cause to `$exception_list`. Exported for unit testing.
export function dropReadOnlyExceptions<T extends FilterableEvent>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string }>
    if (list.some((ex) => ex?.type === 'ReadOnlyModeError')) {
        return null
    }
    return event
}

// Drops `$exception` events raised by deliberate request cancellations. Aborting an
// in-flight fetch rejects it with an `AbortError` DOMException — superseded queries, live
// tail polls cancelled when a new poll starts / the query re-runs / live tail is toggled
// off, and components unmounting mid-request. These are expected, never a bug, so they must
// not clutter error tracking. (`AbortSignal.timeout` rejects with a `TimeoutError`, not an
// `AbortError`, so genuine timeouts are unaffected.) Exported for unit testing.
export function dropRequestCancellationExceptions<T extends FilterableEvent>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string }>
    if (list.some((ex) => ex?.type === 'AbortError')) {
        return null
    }
    return event
}

// Central error-tracking `before_send` filters, applied to every posthog-js init in the app
// (see `loadPostHogJS`). Composing here rather than mutating `before_send` at runtime keeps a
// single owner of the config slot, so filters can't clobber each other.
export const exceptionAutocaptureFilters: BeforeSendFn[] = [dropRequestCancellationExceptions, dropReadOnlyExceptions]
