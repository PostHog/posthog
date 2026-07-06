/**
 * Recognizes the shapes an `import(...)` failure takes across bundlers and browsers. Two families,
 * both symptoms of a stale bundle after a deploy and both recoverable by reloading onto the
 * current bundle.
 *
 * Fetch failures — the chunk file itself could not be loaded:
 *   - webpack: `Error` with `name === 'ChunkLoadError'`
 *   - esbuild/Vite: message contains `'Failed to fetch dynamically imported module'`
 *   - Safari: native `TypeError: Load failed` (no JS stack — see load-failed.tsx known exception)
 *   - Firefox: native `TypeError: NetworkError when attempting to fetch resource.`
 *   - Firefox: native `TypeError: error loading dynamically imported module: <url>` (deferred import of a now-deleted chunk after a deploy)
 *   - WebKit/Safari: `Importing a module script failed.` (module script fails to load, e.g. transient network failure)
 *
 * Link / binding mismatches — the chunk downloaded fine, but a still-cached chunk imports a
 * minified binding a freshly-deployed sibling chunk no longer exports, so the module graph fails
 * to link (a SyntaxError thrown at instantiation time, before any of the chunk's code runs):
 *   - Safari/WebKit: `Importing binding name 'X' is not found.`
 *   - Chrome/V8: `The requested module '<url>' does not provide an export named 'X'`
 *   - Firefox/SpiderMonkey: `import not found: X` / `ambiguous indirect export: X`
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
        message.includes('Importing binding name') ||
        message.includes('does not provide an export named') ||
        message.includes('import not found') ||
        message.includes('ambiguous indirect export')
    )
}
