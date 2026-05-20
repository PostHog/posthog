/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Safari: native `TypeError: Load failed` (no JS stack — see load-failed.tsx known exception)
 *   - Safari (module loader): `TypeError: Importing a module script failed.`
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
        (isTypeError && message.includes('Load failed')) ||
        (isTypeError && message.includes('Importing a module script failed')) ||
        (isTypeError && message.includes('NetworkError when attempting to fetch resource'))
    )
}
