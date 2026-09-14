/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Firefox: native `TypeError: error loading dynamically imported module: <url>` (deferred import of a now-deleted chunk after a deploy)
 *   - WebKit/Safari: `Importing a module script failed.` (module script fails to load, e.g. transient network failure)
 *
 * Safari's/Firefox's generic network TypeErrors (`isGenericNetworkTypeError`) are also a failed
 * `import()`'s shape in those browsers, but the message can't tell that apart from an unrelated
 * failed `fetch()` — so they only count here once `retryImport` has marked them.
 */
const markedChunkLoadErrors = new WeakSet<object>()

export function markAsChunkLoadError(error: unknown): void {
    if (!error || typeof error !== 'object') {
        return
    }
    markedChunkLoadErrors.add(error)
}

/** Safari's/Firefox's native network TypeError shape — ambiguous between a failed `import()` and an unrelated failed `fetch()`. */
export function isGenericNetworkTypeError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    if (err.name !== 'TypeError') {
        return false
    }
    const message = typeof err.message === 'string' ? err.message : ''
    return message.includes('Load failed') || message.includes('NetworkError when attempting to fetch resource')
}

export function isChunkLoadError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    const message = typeof err.message === 'string' ? err.message : ''
    const isTypeError = err.name === 'TypeError'
    return (
        markedChunkLoadErrors.has(error) ||
        err.name === 'ChunkLoadError' ||
        message.includes('Failed to fetch dynamically imported module') ||
        message.includes('Importing a module script failed') ||
        (isTypeError && message.includes('error loading dynamically imported module'))
    )
}
