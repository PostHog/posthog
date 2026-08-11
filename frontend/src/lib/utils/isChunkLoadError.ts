/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Safari: native `TypeError: Load failed` (no JS stack — see load-failed.tsx known exception)
 *   - Firefox: native `TypeError: NetworkError when attempting to fetch resource.`
 *   - Firefox: native `TypeError: error loading dynamically imported module: <url>` (deferred import of a now-deleted chunk after a deploy)
 *   - WebKit/Safari: `Importing a module script failed.` (module script fails to load, e.g. transient network failure)
 *
 * Two more shapes are not matched below, because they only make sense once you know the error came
 * from an `import()`:
 *   - a `SyntaxError` from a chunk that downloaded but failed to parse — `retryImport` recognizes it
 *     with `isModuleParseError`.
 *   - Chromium's bare `TypeError: Failed to fetch`, with no "dynamically imported module" suffix —
 *     `retryImport` recognizes it with `isBareFetchError`.
 * `retryImport` marks both, because there the error is known to come from a lazy import. Matching
 * either message here would swallow a genuine parse bug or a routine API failure in our own code.
 */
const markedChunkLoadErrors = new WeakSet<object>()

export function markAsChunkLoadError(error: unknown): void {
    if (!error || typeof error !== 'object') {
        return
    }
    markedChunkLoadErrors.add(error)
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
        (isTypeError && message.includes('Load failed')) ||
        (isTypeError && message.includes('NetworkError when attempting to fetch resource')) ||
        (isTypeError && message.includes('error loading dynamically imported module'))
    )
}

/**
 * Recognizes a `SyntaxError` from a dynamic `import()` whose chunk downloaded but failed to parse.
 * A deploy deletes the content-hashed chunk, so a proxy answers with an HTML error page, and the
 * browser parses that HTML as JavaScript and rejects it. Each engine reports the parse failure with
 * its own wording:
 *   - Chrome/V8: `Invalid or unexpected token`
 *   - Firefox/SpiderMonkey: `expected expression, got '<'`
 *   - Safari/JavaScriptCore: `Unexpected token '<'`
 *
 * Only `retryImport` calls this, where the error is known to come from an import factory. A real
 * `SyntaxError` in our own code never reaches it, so it is not mistaken for a chunk-load failure.
 */
export function isModuleParseError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    if (err.name !== 'SyntaxError') {
        return false
    }
    const message = typeof err.message === 'string' ? err.message : ''
    return (
        message.includes('Invalid or unexpected token') ||
        message.includes('expected expression, got') ||
        message.includes("Unexpected token '<'")
    )
}

/**
 * Recognizes Chromium's bare `TypeError: Failed to fetch` from a dynamic `import()` whose chunk could
 * not be fetched. Chromium reports this same message for any failed `fetch()`, so `isChunkLoadError`
 * must not match it globally — a routine API blip would turn into a full-page reload. Only `retryImport`
 * calls this, where the error is known to come from an import factory, so the fetch that failed is the
 * chunk fetch.
 */
export function isBareFetchError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    const message = typeof err.message === 'string' ? err.message : ''
    return err.name === 'TypeError' && message.includes('Failed to fetch')
}
