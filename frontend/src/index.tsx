import '~/styles'

import './buffer-polyfill'

import { Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'

import { retryImport } from 'lib/utils/retryImport'

import { RootErrorBoundary } from './RootErrorBoundary'
import { ChunkLoadErrorBoundary } from './scenes/ChunkLoadErrorBoundary'

// Lazy-load App so the entry chunk stays minimal: the entire transitive dependency
// graph (kea, posthog-js, scene logic, UI components) is only fetched when it renders.
// bootApp() runs the chunk's one-time boot side effects (posthog-js, kea) after the
// chunk loads and before <App /> first renders.
const App = lazy(() =>
    retryImport(() => import('scenes/App')).then((mod) => {
        mod.bootApp()
        return { default: mod.App }
    })
)

function renderApp(): void {
    const root = document.getElementById('root')
    if (!root) {
        console.error('Attempted, but could not render PostHog app because <div id="root" /> is not found.')
        return
    }
    createRoot(root).render(
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
