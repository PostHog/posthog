import '~/styles'

import React from 'react'
import ReactDOM from 'react-dom'

import { App } from 'scenes/App'
import { initKea } from './initKea'

import { loadPostHogJS } from './loadPostHogJS'
import { ErrorBoundary } from './layout/ErrorBoundary'

loadPostHogJS()
initKea()

function renderApp(): void {
    const root = document.getElementById('root')
    if (root) {
        ReactDOM.render(
            <ErrorBoundary>
                <App />
            </ErrorBoundary>,
            root
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
