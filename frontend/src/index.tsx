import '~/styles'

import './buffer-polyfill'

import React, { Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'

// Lazy-load App — defers importing the entire transitive dependency graph
// (React wrappers, kea, posthog-js, scene logic, all UI components) until
// the component actually renders. The entry chunk stays minimal.
const App = lazy(() => import('scenes/App'))

function renderApp(): void {
    const root = document.getElementById('root')
    if (root) {
        createRoot(root).render(
            <Suspense
                fallback={
                    <div className="Spinner">
                        <div className="Spinner__inner" />
                    </div>
                }
            >
                <App />
            </Suspense>
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
