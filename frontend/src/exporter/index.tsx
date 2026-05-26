import '~/styles'
import './Exporter.scss'

import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import { createRoot } from 'react-dom/client'

import { Exporter } from '~/exporter/Exporter'
import { ExportType, ExportedData } from '~/exporter/types'
import { initKea } from '~/initKea'
import { loadPostHogJS } from '~/loadPostHogJS'

import { ErrorBoundary } from '../layout/ErrorBoundary'

const exportedData: ExportedData = window.POSTHOG_EXPORTED_DATA

// Disable tracking for shared dashboards / insights / embeds — those iframes can be embedded on
// our customers' sites, and tracking there would log their visitors to app.posthog.com.
// The `interview` scene is the exception: it's our own hosted public page, opened by an invitee
// on a link we sent. We want pageviews + replay to measure the invite-to-call funnel.
if (exportedData?.type !== ExportType.Interview) {
    window.JS_POSTHOG_API_KEY = undefined
} else {
    // The URL embeds the SharingConfiguration access token (/interview/<token>/), and posthog-js
    // captures `window.location` for `$current_url` / `$pathname` / `$referrer` on every pageview
    // and inside session replays. Without scrubbing, anyone with read access to those events or
    // replays would see the token and could reuse it to start a fresh interview call as the
    // invitee. Rewrite the URL via `replaceState` before posthog-js initializes so the captured
    // values never include the token — the client reads the token from `exportedData.accessToken`
    // and does not depend on `window.location`.
    try {
        const redactedPath = window.location.pathname.replace(/\/interview\/[^/?#]+/, '/interview/<redacted>')
        if (redactedPath !== window.location.pathname) {
            window.history.replaceState(null, '', redactedPath + window.location.search + window.location.hash)
        }
    } catch {
        // History API unavailable — fall back to disabling tracking entirely rather than risk
        // the token landing in captured events.
        window.JS_POSTHOG_API_KEY = undefined
    }
}

loadPostHogJS()
initKea({ replaceInitialPathInWindow: false })

// On Chrome + Windows, the country flag emojis don't render correctly. This is a polyfill for that.
// It won't be applied on other platforms.
//
// NOTE: The first argument is the name of the polyfill to use. This is used to set the font family in our CSS.
// Make sure to update the font family in the CSS if you change this.
polyfillCountryFlagEmojis('Emoji Flags Polyfill')

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
