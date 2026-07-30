import { registerNotebookLinkDrag } from 'scenes/notebooks/AddToNotebook/registerNotebookLinkDrag'

import { initKea } from '../initKea'
import { loadPostHogJS } from '../loadPostHogJS'

let appBooted = false

/**
 * One-time boot side effects for the app, called from the entry's lazy factory
 * (frontend/src/index.tsx) after the app chunk loads and before <App /> first renders.
 * A function rather than module-scope statements so that merely importing it
 * (storybook stories, jest) stays side-effect-free — the test harnesses manage their
 * own kea context, and an import-time initKea() would wipe it.
 * Lives outside App.tsx so scenes/App keeps component-only exports and stays a React
 * Fast Refresh boundary; with a mixed-export App.tsx, HMR invalidations cascade into
 * src/index.tsx and force a full page reload on routine edits.
 */
export function bootApp(): void {
    if (appBooted) {
        return
    }
    appBooted = true

    loadPostHogJS()
    // Kea must initialize before any component mounts
    initKea()
    // Link resolves its drag-to-notebook behavior through a seam so bundles without
    // notebooks (toolbar, exporter) don't ship them; the app opts in here
    registerNotebookLinkDrag()

    const idle =
        typeof window.requestIdleCallback === 'function'
            ? window.requestIdleCallback.bind(window)
            : (cb: () => void) => setTimeout(cb, 200)

    idle(() => {
        void import('./session-recordings/player/snapshot-processing/DecompressionWorkerManager')
            .then(({ preWarmDecompression }) => preWarmDecompression())
            .catch((error) => {
                console.warn('[App] Failed to load DecompressionWorkerManager for pre-warm:', error)
            })

        // On Chrome + Windows, the country flag emojis don't render correctly. This polyfill fixes that.
        // NOTE: The first argument sets the polyfill's font family name, which our CSS references —
        // keep the two in sync. Detection is canvas-based and can throw on some browser states
        // (e.g. Safari/macOS); it's purely cosmetic and best-effort.
        void import('country-flag-emoji-polyfill')
            .then(({ polyfillCountryFlagEmojis }) => polyfillCountryFlagEmojis('Emoji Flags Polyfill'))
            .catch((error) => {
                console.warn('[App] Country flag emoji polyfill failed:', error)
            })
    })
}
