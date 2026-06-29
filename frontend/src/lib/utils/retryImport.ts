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
 *
 * `await factory()` normalizes the factory: a synchronous return value or a synchronous throw is
 * handled just like a resolved/rejected promise.
 */
export async function retryImport<T>(factory: () => T, retries = 2, baseDelayMs = 300): Promise<Awaited<T>> {
    try {
        return await factory()
    } catch (error) {
        if (retries <= 0 || !isChunkLoadError(error)) {
            throw error
        }
        await new Promise<void>((resolve) => setTimeout(resolve, baseDelayMs))
        return retryImport(factory, retries - 1, baseDelayMs * 2)
    }
}
