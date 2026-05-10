/**
 * Recognizes the various shapes a failed `import(...)` can take across bundlers and browsers:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Safari: native `TypeError: Load failed` (no JS stack — see load-failed.tsx known exception)
 */
export function isChunkLoadError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    const message = typeof err.message === 'string' ? err.message : ''
    return (
        err.name === 'ChunkLoadError' ||
        message.includes('Failed to fetch dynamically imported module') ||
        (err.name === 'TypeError' && message.includes('Load failed'))
    )
}
