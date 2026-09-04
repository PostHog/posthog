import { ComponentType, LazyExoticComponent, lazy } from 'react'

import { isChunkLoadError, markAsChunkLoadError } from 'lib/utils/isChunkLoadError'

function isMinifiedBootModuleEvaluationError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const { name, message } = error as { name?: string; message?: string }
    return name === 'TypeError' && typeof message === 'string' && /^[A-Za-z_$] is not a function$/.test(message)
}

/**
 * A dynamic `import()` can reject with a value that is not an object — Firefox has rejected with
 * `undefined`. Such a value has no message and no stack, and `isChunkLoadError` cannot classify it,
 * so every layer above treats a load failure as an application crash and skips the reload recovery.
 * Turn it into a real `Error` and mark it as a chunk-load failure.
 */
function normalizeImportRejection(error: unknown): unknown {
    if (error && typeof error === 'object') {
        return error
    }
    const normalized = new Error(`Dynamic import rejected with a non-object value: ${String(error)}`)
    markAsChunkLoadError(normalized)
    return normalized
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
    } catch (rawError) {
        const error = normalizeImportRejection(rawError)
        if (retries <= 0 || !isChunkLoadError(error)) {
            throw error
        }
        await new Promise<void>((resolve) => setTimeout(resolve, baseDelayMs))
        return retryImport(factory, retries - 1, baseDelayMs * 2)
    }
}

export async function retryBootImport<T>(factory: () => T): Promise<Awaited<T>> {
    try {
        return await retryImport(factory)
    } catch (error) {
        if (isMinifiedBootModuleEvaluationError(error)) {
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
