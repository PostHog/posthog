import { ComponentType, LazyExoticComponent, lazy } from 'react'

import { isChunkLoadError, markAsChunkLoadError } from 'lib/utils/isChunkLoadError'

function isMinifiedBootModuleEvaluationError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const { name, message } = error as { name?: string; message?: string }
    // A minified identifier, alone or with one property access: `g is not a function`,
    // `i.bootApp is not a function`. Deliberately narrow, so a real application bug on a
    // readable name is not mistaken for a stale chunk.
    return (
        name === 'TypeError' && typeof message === 'string' && /^[A-Za-z_$](\.[\w$]+)? is not a function$/.test(message)
    )
}

/**
 * Reads an export that the boot path needs off a freshly-imported module.
 *
 * A stale chunk can resolve without the export it should carry, and the failure then surfaces where
 * neither `retryBootImport` nor `isChunkLoadError` sees it: a call to a missing function throws
 * inside the import's `.then` handler, and a missing component reaches React as an undefined element
 * type. Either way `ChunkLoadErrorBoundary` skips its one-time reload and the person gets the fatal
 * error screen. Mark the failure as a chunk-load error, so the boundary reloads once.
 */
export function requireBootExport<T extends object, K extends keyof T>(module: T, exportName: K): NonNullable<T[K]> {
    const value = module[exportName]
    if (typeof value !== 'function') {
        const error = new TypeError(`Boot chunk resolved without its ${String(exportName)} export`)
        markAsChunkLoadError(error)
        throw error
    }
    return value as NonNullable<T[K]>
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
