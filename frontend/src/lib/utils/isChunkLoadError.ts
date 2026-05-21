/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Vite (alternate): message contains `'error loading dynamically imported module'`
 *   - Safari: native `TypeError: Load failed` (no JS stack — see load-failed.tsx known exception)
 *   - Firefox: native `TypeError: NetworkError when attempting to fetch resource.`
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
        message.includes('error loading dynamically imported module') ||
        (isTypeError && message.includes('Load failed')) ||
        (isTypeError && message.includes('NetworkError when attempting to fetch resource'))
    )
}

// `g is not a function`, `h is not a function`, etc. — a stale chunk can resolve to a
// degenerate module whose minified single-letter exports are no longer functions, and
// React then throws inside `createRoot.render` before any boundary mounts. We only
// match short minified identifiers (1-4 chars) at the start of the message so a real
// `something.callback is not a function` bug doesn't trigger a reload.
const SHORT_MINIFIED_NOT_A_FUNCTION_PATTERN = /^[a-zA-Z_$][\w$]{0,3} is not a function/

/**
 * Heuristically recognises the runtime shape of a stale-chunk failure: a `TypeError`
 * with a short minified identifier (e.g. `g is not a function`). This is broader and
 * less certain than `isChunkLoadError`, so callers should reserve it for situations
 * where a reload-once recovery is appropriate (e.g. inside React.lazy / Suspense
 * boundaries or the boot-time entry point in `index.tsx`).
 */
export function isLikelyStaleChunkRuntimeError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    if (err.name !== 'TypeError') {
        return false
    }
    const message = typeof err.message === 'string' ? err.message : ''
    return SHORT_MINIFIED_NOT_A_FUNCTION_PATTERN.test(message)
}
