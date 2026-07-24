import { BeforeSendFn } from 'posthog-js'

// posthog-js exposes a single `before_send` slot, but several features need to drop or
// mutate events before they leave the browser (network-error noise, read-only mode, the
// exporter's token redaction). They compose through this registry instead of clobbering
// each other's `set_config({ before_send })`. `composedBeforeSend` is installed once at
// init in `loadPostHogJS`; everything else registers a filter via `addBeforeSendFilter`.
const filters = new Set<BeforeSendFn>()

export const composedBeforeSend: BeforeSendFn = (event) => {
    let result = event
    for (const filter of filters) {
        if (result === null) {
            return null
        }
        result = filter(result)
    }
    return result
}

/** Register a `before_send` filter. Returns a disposer that removes it again. */
export function addBeforeSendFilter(filter: BeforeSendFn): () => void {
    filters.add(filter)
    return () => {
        filters.delete(filter)
    }
}

// Drops `$exception` events for `ApiNetworkError` — benign browser network failures
// (dropped connections, ad blockers, navigations mid-request) that surface as generic
// fetch `TypeError`s ("Load failed" / "Failed to fetch"). They are client-side noise,
// not real bugs, so we keep them out of error tracking. The chain walk catches wrapped
// errors (e.g. `new Error('...', { cause: networkErr })`). Exported for unit testing.
export function dropNetworkErrors<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string }>
    if (list.some((ex) => ex?.type === 'ApiNetworkError')) {
        return null
    }
    return event
}
