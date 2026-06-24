import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

/**
 * Re-attempts a dynamic `import()` on a transient chunk-load failure before giving up.
 *
 * Most "Failed to fetch dynamically imported module" errors are transient — a network blip,
 * or a fetch racing an auth redirect — and succeed on a second attempt without a full-page
 * reload, so page state is preserved. Non-chunk errors and exhausted retries rethrow, so the
 * existing reload/error recovery (ChunkLoadErrorBoundary, sceneLogic) still runs.
 *
 * Bounded by a decrementing counter (1 + `retries` attempts), so it cannot loop.
 */
export function retryImport<T>(factory: () => Promise<T>, retries = 2, baseDelayMs = 300): Promise<T> {
    return factory().catch((error) => {
        if (retries <= 0 || !isChunkLoadError(error)) {
            throw error
        }
        return new Promise<void>((resolve) => setTimeout(resolve, baseDelayMs)).then(() =>
            retryImport(factory, retries - 1, baseDelayMs * 2)
        )
    })
}
