import '~/styles'
import './Exporter.scss'

// The relative path keeps this with the side-effect imports when imports are sorted, so it evaluates
// before any module that builds a zod schema. See lib/configureZod.
import '../lib/configureZod'

import { createRoot } from 'react-dom/client'

import { polyfillCountryFlags } from 'lib/countryFlagEmojiPolyfill'

import { Exporter } from '~/exporter/Exporter'
import { ExportedData } from '~/exporter/types'
import { initKea } from '~/initKea'
import { loadPostHogJS } from '~/loadPostHogJS'

import { ErrorBoundary } from '../layout/ErrorBoundary'

const exportedData: ExportedData = window.POSTHOG_EXPORTED_DATA

// Disable tracking for shared dashboards / insights / embeds — those iframes can be embedded on
// our customers' sites, and tracking there would log their visitors to app.posthog.com.
window.JS_POSTHOG_API_KEY = undefined

loadPostHogJS()
initKea({ replaceInitialPathInWindow: false })

// On Chrome + Windows, the country flag emojis don't render correctly. This is a polyfill for that.
// It won't be applied on other platforms.
//
// The polyfill runs canvas-based feature detection (getImageData) which can throw on some browser
// states (e.g. Safari/macOS). It's purely cosmetic and best-effort, so swallow any failure.
try {
    polyfillCountryFlags()
} catch (error) {
    console.warn('[exporter] Country flag emoji polyfill detection failed:', error)
}

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
