import '~/styles'

import './buffer-polyfill'

import React, { Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'

import { retryImport } from 'lib/utils/retryImport'

// Lazy-load App so the entry chunk stays minimal: the entire transitive dependency
// graph (kea, posthog-js, scene logic, UI components) is only fetched when it renders.
const App = lazy(() => retryImport(() => import('scenes/App')).then((mod) => ({ default: mod.App })))

/**
 * Dependency-free error boundary for App chunk load failures. The full ErrorBoundary
 * lives inside the App chunk, so it can't guard the load of that same chunk.
 */
class RootErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean }> {
    override state = { hasError: false }

    static getDerivedStateFromError(): { hasError: boolean } {
        return { hasError: true }
    }

    override render(): React.ReactNode {
        if (this.state.hasError) {
            return (
                <div className="Preloader">
                    <div>
                        PostHog failed to load.{' '}
                        <button className="underline" onClick={() => window.location.reload()}>
                            Reload the page
                        </button>{' '}
                        to try again.
                    </div>
                </div>
            )
        }
        return this.props.children
    }
}

function renderApp(): void {
    const root = document.getElementById('root')
    if (root) {
        createRoot(root).render(
            <RootErrorBoundary>
                <Suspense
                    fallback={
                        <div className="Preloader">
                            <div className="Preloader__inner" />
                        </div>
                    }
                >
                    <App />
                </Suspense>
            </RootErrorBoundary>
        )
    } else {
        console.error('Attempted, but could not render PostHog app because <div id="root" /> is not found.')
    }
}

// Render react only when DOM has loaded - javascript might be cached and loaded before the page is ready.
if (document.readyState !== 'loading') {
    renderApp()
} else {
    document.addEventListener('DOMContentLoaded', renderApp)
}
