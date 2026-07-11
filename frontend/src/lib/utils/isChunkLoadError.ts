/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Safari: native `TypeError: Load failed` (no JS stack — see load-failed.tsx known exception)
 *   - Firefox: native `TypeError: NetworkError when attempting to fetch resource.`
 *   - Firefox: native `TypeError: error loading dynamically imported module: <url>` (deferred import of a now-deleted chunk after a deploy)
 *   - WebKit/Safari: `Importing a module script failed.` (module script fails to load, e.g. transient network failure)
 *   - Chromium: `TypeError: '' is not a valid JavaScript MIME type` (deleted content-hashed chunk served with an empty content-type after a deploy)
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
        (isTypeError && message.includes('error loading dynamically imported module')) ||
        (isTypeError && message.includes('is not a valid JavaScript MIME type'))
    )
}
