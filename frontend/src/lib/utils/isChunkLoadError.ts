/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Firefox: native `TypeError: error loading dynamically imported module: <url>` (deferred import of a now-deleted chunk after a deploy)
 *   - WebKit/Safari: `Importing a module script failed.` (module script fails to load, e.g. transient network failure)
 *   - stable chunk build: a native `TypeError` that names an `@c/` specifier the page's import map does not hold
 *     (a logged-out page gets only the logged-out part of the map, see posthog/stable_chunks.py)
 *
 * Safari's/Firefox's generic network TypeErrors (`isGenericNetworkTypeError`) are also a failed
 * `import()`'s shape in those browsers, but the message can't tell that apart from an unrelated
 * failed `fetch()` — so they only count here once `retryImport` has marked them. The same holds
 * for a `SyntaxError` from a chunk that fails to parse.
 */
const markedChunkLoadErrors = new WeakSet<object>()

// Chrome, Firefox and Safari quote the specifier with ", “ or ' in their unresolved-specifier messages.
const UNMAPPED_STABLE_CHUNK_SPECIFIER = /["“'](@c\/[A-Za-z0-9]+)["”']/

export function markAsChunkLoadError(error: unknown): void {
    if (!error || typeof error !== 'object') {
        return
    }
    markedChunkLoadErrors.add(error)
}

/** Extract error name and message safely from an error-like object. */
function getErrorInfo(error: unknown): { name: string; message: string } | null {
    if (!error || typeof error !== 'object') {
        return null
    }
    const err = error as { name?: string; message?: string }
    const name = err.name ?? ''
    const message = typeof err.message === 'string' ? err.message : ''
    return { name, message }
}

/** Safari's/Firefox's native network TypeError shape — ambiguous between a failed `import()` and an unrelated failed `fetch()`. */
export function isGenericNetworkTypeError(error: unknown): boolean {
    const info = getErrorInfo(error)
    if (!info || info.name !== 'TypeError') {
        return false
    }
    return (
        info.message.includes('Load failed') || info.message.includes('NetworkError when attempting to fetch resource')
    )
}

export function unmappedStableChunkSpecifier(error: unknown): string | null {
    const info = getErrorInfo(error)
    if (info?.name !== 'TypeError') {
        return null
    }
    return UNMAPPED_STABLE_CHUNK_SPECIFIER.exec(info.message)?.[1] ?? null
}

export function isChunkLoadError(error: unknown): boolean {
    const info = getErrorInfo(error)
    if (!info) {
        return false
    }
    const isTypeError = info.name === 'TypeError'
    return (
        markedChunkLoadErrors.has(error as object) ||
        info.name === 'ChunkLoadError' ||
        info.message.includes('Failed to fetch dynamically imported module') ||
        info.message.includes('Importing a module script failed') ||
        (isTypeError && info.message.includes('error loading dynamically imported module')) ||
        unmappedStableChunkSpecifier(error) !== null
    )
}
