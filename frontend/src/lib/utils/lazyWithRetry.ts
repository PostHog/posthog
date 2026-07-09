import { ComponentType, lazy, LazyExoticComponent } from 'react'

import { retryImport } from 'lib/utils/retryImport'

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
