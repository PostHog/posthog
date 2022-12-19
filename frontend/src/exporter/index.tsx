import '~/styles'
import './Exporter.scss'
import ReactDOM from 'react-dom'
import { loadPostHogJS } from '~/loadPostHogJS'
import { initKea } from '~/initKea'
import { Exporter } from '~/exporter/Exporter'
import { ExportedData } from '~/exporter/types'
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
        ReactDOM.render(
            <ErrorBoundary>
                <Exporter {...exportedData} />
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
