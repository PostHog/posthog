import { ComponentProps, ComponentType, LazyExoticComponent, createElement, lazy, useState } from 'react'

import { isChunkLoadError, isGenericNetworkTypeError, markAsChunkLoadError } from 'lib/utils/isChunkLoadError'

function isMinifiedBootModuleEvaluationError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const { name, message } = error as { name?: string; message?: string }
    return name === 'TypeError' && typeof message === 'string' && /^[A-Za-z_$] is not a function$/.test(message)
}

function isSyntaxError(error: unknown): boolean {
    return !!error && typeof error === 'object' && (error as { name?: string }).name === 'SyntaxError'
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
        // A truncated or corrupted chunk fails to parse. The browser caches the failed module per URL,
        // so a retry gets the same error. Only a page reload fetches the chunk again.
        if (isSyntaxError(error)) {
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

export interface PreloadableComponent<T extends ComponentType<any>> {
    Component: (props: ComponentProps<T>) => JSX.Element
    /** Starts the chunk download. Resolves when it ends, also on a failure, which the render path reports. */
    preload: () => Promise<void>
}

/**
 * `lazyWithRetry` plus a `preload()` that a logic can call as soon as it knows the component will render,
 * so the chunk downloads in parallel with the data. A component that mounts after the chunk has loaded
 * renders at once and never shows its Suspense fallback.
 */
export function lazyWithPreload<T extends ComponentType<any>>(
    factory: () => Promise<{ default: T }>
): PreloadableComponent<T> {
    let loaded: T | null = null
    let pending: Promise<{ default: T }> | null = null
    const load = (): Promise<{ default: T }> => {
        pending ??= retryImport(factory).then(
            (module) => {
                loaded = module.default
                return module
            },
            (error) => {
                pending = null
                // React caches a rejection inside the lazy wrapper, so a remount after a failure needs a new one.
                Lazy = lazy(load)
                throw error
            }
        )
        return pending
    }
    let Lazy = lazy(load)

    function Component(props: ComponentProps<T>): JSX.Element {
        // Decided once per mount: switching from the lazy wrapper to the loaded component would remount it.
        const [Resolved] = useState(() => loaded ?? Lazy)
        return createElement(Resolved as ComponentType<ComponentProps<T>>, props)
    }

    return {
        Component,
        preload: () =>
            load().then(
                () => undefined,
                () => undefined
            ),
    }
}
