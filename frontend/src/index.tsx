import '~/styles'

import './buffer-polyfill'

import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'
import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import { getContext } from 'kea'
import posthog from 'posthog-js'
import { createRoot } from 'react-dom/client'

import { PostHogProvider } from '@posthog/react'

import { isChunkLoadError, isLikelyStaleChunkRuntimeError } from 'lib/utils/isChunkLoadError'
import { reloadOnceForStaleChunk } from 'lib/utils/reloadOnceForStaleChunk'
import { App } from 'scenes/App'

import { initKea } from './initKea'
import { ErrorBoundary } from './layout/ErrorBoundary'
import { loadPostHogJS } from './loadPostHogJS'

loadPostHogJS()
initKea()

/**
 * Boot-time recovery for stale-chunk failures: if a deploy invalidates the chunk hashes
 * referenced by an old cached `index.html`, the dynamic imports kicked off by
 * `React.lazy` (or the idle pre-warm below) can fail synchronously inside `createRoot.render`
 * before any React boundary mounts. When that happens, no in-tree boundary — including the
 * `ChunkLoadErrorBoundary` — gets a chance to recover, and the user sees a blank screen.
 *
 * We mirror the boundary's reload-once behavior here for errors that escape the React tree:
 *   1. A try/catch around the synchronous render call.
 *   2. Global `error` / `unhandledrejection` listeners for async failures from idle imports.
 * All three paths share the same localStorage guard, so we never reload more than once.
 */
function maybeReloadForStaleChunk(error: unknown): boolean {
    if (!isChunkLoadError(error) && !isLikelyStaleChunkRuntimeError(error)) {
        return false
    }
    if (reloadOnceForStaleChunk()) {
        console.warn('[index] Boot-time chunk-load failure (likely stale deploy); reloading.', error)
        return true
    }
    console.error('[index] Recently reloaded; surfacing boot-time chunk error.', error)
    return false
}

if (typeof window !== 'undefined') {
    window.addEventListener('error', (event) => {
        if (maybeReloadForStaleChunk(event.error)) {
            event.preventDefault()
        }
    })
    window.addEventListener('unhandledrejection', (event) => {
        if (maybeReloadForStaleChunk(event.reason)) {
            event.preventDefault()
        }
    })
}

const idle =
    typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function'
        ? window.requestIdleCallback.bind(window)
        : (cb: () => void) => setTimeout(cb, 200)

idle(() => {
    void import('./scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager')
        .then(({ preWarmDecompression }) => preWarmDecompression())
        .catch((error) => {
            console.warn('[index] Failed to load DecompressionWorkerManager for pre-warm:', error)
        })
})

// On Chrome + Windows, the country flag emojis don't render correctly. This is a polyfill for that.
// It won't be applied on other platforms.
//
// NOTE: The first argument is the name of the polyfill to use. This is used to set the font family in our CSS.
// Make sure to update the font family in the CSS if you change this.
polyfillCountryFlagEmojis('Emoji Flags Polyfill')

// Expose `window.getReduxState()` to make snapshots to storybook easy
if (typeof window !== 'undefined') {
    // Disabled in production to prevent leaking secret data, personal API keys, etc
    if (process.env.NODE_ENV === 'development') {
        ;(window as any).getReduxState = () => getContext().store.getState()
    } else {
        ;(window as any).getReduxState = () => 'Disabled outside development!'
    }
}

function renderApp(): void {
    const root = document.getElementById('root')
    if (!root) {
        console.error('Attempted, but could not render PostHog app because <div id="root" /> is not found.')
        return
    }
    try {
        createRoot(root).render(
            <ErrorBoundary>
                <PostHogProvider client={posthog}>
                    <BaseTooltip.Provider delay={500} closeDelay={0} timeout={400}>
                        <App />
                    </BaseTooltip.Provider>
                </PostHogProvider>
            </ErrorBoundary>
        )
    } catch (error) {
        if (maybeReloadForStaleChunk(error)) {
            return
        }
        throw error
    }
}

// Render react only when DOM has loaded - javascript might be cached and loaded before the page is ready.
if (document.readyState !== 'loading') {
    renderApp()
} else {
    document.addEventListener('DOMContentLoaded', renderApp)
}
