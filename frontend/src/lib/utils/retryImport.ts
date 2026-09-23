import { ComponentType, LazyExoticComponent, lazy } from 'react'

import { isChunkLoadError, isGenericNetworkTypeError, markAsChunkLoadError } from 'lib/utils/isChunkLoadError'

/**
 * A chunk that loads but then evaluates against a cross-chunk binding from a previous deploy
 * throws on a minified local, so the message names a bundler identifier instead of anything in
 * our source. Each engine words that differently:
 *   - V8 call shape: `g is not a function`
 *   - Firefox property access: `can't access property "message", _ is undefined`
 * Both patterns require a single-character subject, which is what makes them specific to a
 * bundler local. V8's property-access wording (`Cannot read properties of undefined (reading
 * 'message')`) names no subject at all, so it also matches an ordinary bug in a module's
 * top-level code — it stays out, because classifying one of those would reload the page
 * instead of reporting the bug.
 */
const MINIFIED_MODULE_EVALUATION_MESSAGES = [
    /^[A-Za-z_$] is not a function$/,
    /^can't access property "[^"]+", [A-Za-z_$] is (undefined|null)$/,
]

function isMinifiedModuleEvaluationError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const { name, message } = error as { name?: string; message?: string }
    if (name !== 'TypeError' || typeof message !== 'string') {
        return false
    }
    return MINIFIED_MODULE_EVALUATION_MESSAGES.some((pattern) => pattern.test(message))
}

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
        if (isMinifiedModuleEvaluationError(error)) {
            // The chunk already loaded, so a re-attempt evaluates the same stale binding again.
            // Classify it for ChunkLoadErrorBoundary and give up on this attempt.
            markAsChunkLoadError(error)
            throw error
        }
        if (!isChunkLoadError(error) && !isGenericNetworkTypeError(error)) {
            throw error
        }
        // Mark as a chunk load error so downstream boundaries recognize it if retries fail.
        markAsChunkLoadError(error)
        if (retries <= 0) {
            throw error
        }
        await new Promise<void>((resolve) => setTimeout(resolve, baseDelayMs))
        return retryImport(factory, retries - 1, baseDelayMs * 2)
    }
}

/**
 * Drop-in replacement for `React.lazy` that retries a transient chunk-load failure before giving up.
 *
 * Lazily-loaded chunks are content-hashed per deploy, so a tab opened before a deploy can fail to
 * fetch a now-deleted chunk ("Failed to fetch dynamically imported module"). `retryImport` re-attempts
 * the import a few times (preserving page state) before the error propagates to `ChunkLoadErrorBoundary`
 * for a one-time reload. This is the same wrapping the scene loader (`sceneLogic`) and the root `App`
 * lazy import already use; this helper just makes it the easy default for any lazily-loaded component.
 *
 * Prefer this over `lazy(() => import(...))`.
 */
export function lazyWithRetry<T extends ComponentType<any>>(
    factory: () => Promise<{ default: T }>
): LazyExoticComponent<T> {
    return lazy(() => retryImport(factory))
}
