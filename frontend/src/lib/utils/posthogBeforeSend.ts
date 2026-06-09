import posthog, { BeforeSendFn, CaptureResult } from 'posthog-js'

// posthog-js exposes a single `before_send` slot that `set_config` replaces wholesale.
// Several independent parts of the app need to drop events before they leave the browser
// (benign chunk-load errors at startup, `ReadOnlyModeError` while read-only mode is mounted,
// the exporter's interview-token redaction, ...). Routing every filter through this registry
// composes them into one chained function and keeps posthog pointed at it, so registering or
// unregistering one filter never clobbers another.
//
// Filters run in registration order; the first to return `null` short-circuits and drops the
// event, matching the posthog-js `before_send` contract.
const filters = new Set<BeforeSendFn>()

const runRegisteredFilters: BeforeSendFn = (event) => {
    let current: CaptureResult | null = event
    for (const filter of filters) {
        if (current === null) {
            break
        }
        current = filter(current)
    }
    return current
}

/**
 * Register a `before_send` filter. Returns an unregister function — call it on teardown so the
 * filter stops running without disturbing the others.
 */
export function registerBeforeSendFilter(filter: BeforeSendFn): () => void {
    filters.add(filter)
    posthog.set_config({ before_send: runRegisteredFilters })
    return () => {
        filters.delete(filter)
        posthog.set_config({ before_send: runRegisteredFilters })
    }
}
