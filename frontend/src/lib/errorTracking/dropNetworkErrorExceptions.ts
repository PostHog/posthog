/**
 * Drops `$exception` events whose chain contains a `NetworkError` — the transient fetch failures
 * `handleFetch` wraps (Safari `TypeError: Load failed`, etc.). These are high-volume noise outside
 * our control that bury real defects in error tracking, so we suppress them at the single choke
 * point every capture path flows through. Mirrors `dropReadOnlyExceptions`. The chain walk (`some`)
 * catches the original browser `TypeError` carried on the wrapper as `cause`. Exported for testing.
 */
export function dropNetworkErrorExceptions<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string }>
    if (list.some((ex) => ex?.type === 'NetworkError')) {
        return null
    }
    return event
}
