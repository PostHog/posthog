import '~/styles'
import './Exporter.scss'

import { createRoot } from 'react-dom/client'

import { Exporter } from '~/exporter/Exporter'
import { ExportedData } from '~/exporter/types'
import { initKea } from '~/initKea'
import { loadPostHogJS } from '~/loadPostHogJS'

import { ErrorBoundary } from '../layout/ErrorBoundary'

// Disable tracking for all exports and embeds.
// This is explicitly set as to not track our customers' customers data.
// Without it, embeds of self-hosted iframes will log metrics to app.posthog.com.
window.JS_POSTHOG_API_KEY = undefined

loadPostHogJS()
initKea()

const exportedData: ExportedData = window.POSTHOG_EXPORTED_DATA

function renderApp(): void {
    const root = document.getElementById('root')
    if (root) {
        createRoot(root).render(
            <ErrorBoundary>
                <Exporter {...exportedData} />
            </ErrorBoundary>
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
