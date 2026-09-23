import { ComponentType, LazyExoticComponent, lazy } from 'react'

import { isChunkLoadError, isGenericNetworkTypeError, markAsChunkLoadError } from 'lib/utils/isChunkLoadError'

/**
 * A chunk that loads but then evaluates against a cross-chunk binding from a previous deploy
 * throws on a minified local, which each engine words differently:
 *   - V8 call shape: `g is not a function`
 *   - Firefox property access: `can't access property "message", _ is undefined`
 * Both patterns require a single-character subject, which is what ties them to a bundler local.
 * V8's property-access wording (`Cannot read properties of undefined (reading 'message')`) names
 * no subject, so it matches an ordinary bug in a module's top-level code just as well. It stays
 * out: classifying one of those would reload the page instead of reporting the bug.
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
 * `retryImport` for an import a full-page reload can recover: the app boot modules, and the
 * per-route scene chunks.
 *
 * A stale evaluation in either one leaves no working app around the failure, so these two alone
 * accept the `isMinifiedModuleEvaluationError` guess: a wrong guess costs a reload of a page the
 * user cannot use. Every other caller keeps the original error, so an ordinary bug in a module's
 * top-level code still reports rather than turning into a reload.
 *
 * There is no retry for this class: the chunk already loaded, so a re-attempt evaluates the same
 * stale binding.
 */
export async function retryReloadableImport<T>(factory: () => T): Promise<Awaited<T>> {
    try {
        return await retryImport(factory)
    } catch (error) {
        if (isMinifiedModuleEvaluationError(error)) {
            markAsChunkLoadError(error)
        }
        throw error
    }
}

/**
 * Drop-in replacement for `React.lazy` that retries a transient chunk-load failure before giving up.
 *
 * Lazily-loaded chunks are content-hashed per deploy, so a tab opened before a deploy can fail to
 * fetch a now-deleted chunk ("Failed to fetch dynamically imported module"). `retryImport` re-attempts
 * the import a few times (preserving page state) before the error propagates to `ChunkLoadErrorBoundary`
 * for a one-time reload. This is the same wrapping the root `App` lazy import already uses; this
 * helper just makes it the easy default for any lazily-loaded component.
 *
 * Prefer this over `lazy(() => import(...))`.
 */
export function lazyWithRetry<T extends ComponentType<any>>(
    factory: () => Promise<{ default: T }>
): LazyExoticComponent<T> {
    return lazy(() => retryImport(factory))
}
