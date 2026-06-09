/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Safari: native `TypeError: Load failed` (no JS stack — see load-failed.tsx known exception)
 *   - Firefox: native `TypeError: NetworkError when attempting to fetch resource.`
 *   - Firefox: native `TypeError: error loading dynamically imported module: <url>` (deferred import of a now-deleted chunk after a deploy)
 *   - WebKit/Safari: `Importing a module script failed.` (module script fails to load, e.g. transient network failure)
 */
export function isChunkLoadError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    const message = typeof err.message === 'string' ? err.message : ''
    const isTypeError = err.name === 'TypeError'
    return (
        err.name === 'ChunkLoadError' ||
        message.includes('Failed to fetch dynamically imported module') ||
        message.includes('Importing a module script failed') ||
        (isTypeError && message.includes('Load failed')) ||
        (isTypeError && message.includes('NetworkError when attempting to fetch resource')) ||
        (isTypeError && message.includes('error loading dynamically imported module'))
    )
}

/**
 * `before_send` filter that drops `$exception` events whose error is a recognized chunk-load
 * failure. These happen when a user on a stale browser tab requests a hashed chunk that a fresh
 * deploy already deleted — the app already recovers by reloading (`sceneLogic`,
 * `ChunkLoadErrorBoundary`), so capturing them as errors is benign stale-deploy noise. The walk
 * over `$exception_list` catches wrapped errors where the chunk-load error is in the cause chain.
 *
 * Exported for unit testing.
 */
export function dropChunkLoadExceptions<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    // posthog-js exception autocapture maps the error name to `type` and message to `value`.
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string; value?: string }>
    if (list.some((ex) => isChunkLoadError({ name: ex?.type, message: ex?.value }))) {
        return null
    }
    return event
}
