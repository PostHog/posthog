import '~/styles'

import './buffer-polyfill'

import { Suspense, lazy } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { consumeDesktopFreshWindowParam } from 'lib/utils/isDesktopApp'
import { retryBootImport } from 'lib/utils/retryImport'

import { RootErrorBoundary } from './RootErrorBoundary'

// Must run before kea-router boots so the desktop app's window-management param never reaches scenes
consumeDesktopFreshWindowParam()
import { ChunkLoadErrorBoundary } from './scenes/ChunkLoadErrorBoundary'

// Lazy-load App so the entry chunk stays minimal: the entire transitive dependency
// graph (kea, posthog-js, scene logic, UI components) is only fetched when it renders.
// bootApp() runs the one-time boot side effects (posthog-js, kea) after the chunks
// load and before <App /> first renders. It lives in its own module so scenes/App
// keeps component-only exports and stays a React Fast Refresh boundary.
const App = lazy(() =>
    Promise.all([retryBootImport(() => import('scenes/App')), retryBootImport(() => import('scenes/bootApp'))]).then(
        ([appModule, bootModule]) => {
            bootModule.bootApp()
            return { default: appModule.App }
        }
    )
)

declare global {
    interface Window {
        __posthogAppRoot?: Root
    }
}

function renderApp(): void {
    const rootElement = document.getElementById('root')
    if (!rootElement) {
        console.error('Attempted, but could not render PostHog app because <div id="root" /> is not found.')
        return
    }
    // Vite 8 can serve this entry module twice after an HMR invalidation reaches it (the script
    // tag's bare URL plus a timestamped copy), and a second createRoot on an already-rooted
    // container crashes React. Reuse one root so a repeat execution re-renders instead.
    const root = (window.__posthogAppRoot ??= createRoot(rootElement))
    root.render(
        <RootErrorBoundary>
            {/* Auto-reloads once on a chunk-load failure (stale deploy). Repeated or non-chunk
                errors bubble to RootErrorBoundary, which reports them and shows the failure UI. */}
            <ChunkLoadErrorBoundary>
                <Suspense
                    fallback={
                        <div className="Preloader" role="status" aria-label="Loading PostHog">
                            <div className="Preloader__inner" />
                        </div>
                    }
                >
                    <App />
                </Suspense>
            </ChunkLoadErrorBoundary>
        </RootErrorBoundary>
    )
}

// Render react only when DOM has loaded - javascript might be cached and loaded before the page is ready.
if (document.readyState !== 'loading') {
    renderApp()
} else {
    document.addEventListener('DOMContentLoaded', renderApp)
}
