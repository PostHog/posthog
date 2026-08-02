/**
 * Drops `$exception` events whose chain contains a `ResponseBodyReadError` — a 2xx response body
 * stream that failed mid-read after the server already answered successfully (dropped connection,
 * proxy hiccup). This is the same noise `initKea`'s loader `onFailure` already skips for kea
 * loaders; this filter covers captures that don't go through a loader (kea listeners, unhandled
 * promise rejections). Mirrors `dropReadOnlyExceptions`. Exported for testing.
 */
export function dropResponseBodyReadExceptions<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string }>
    if (list.some((ex) => ex?.type === 'ResponseBodyReadError')) {
        return null
    }
    return event
}
