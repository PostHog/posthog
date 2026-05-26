import '~/styles'
import './Exporter.scss'

import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import posthog from 'posthog-js'
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
const isInterview = exportedData?.type === ExportType.Interview
if (!isInterview) {
    window.JS_POSTHOG_API_KEY = undefined
}

loadPostHogJS()

if (isInterview) {
    // The URL embeds the SharingConfiguration access token (/interview/<token>/). Redact it from
    // any URL-like property posthog-js would send so a viewer of captured events can't reuse the
    // token to start a fresh call as the invitee. Session replay's URL metadata is a separate
    // surface and is not covered by `before_send` — we accept that tradeoff for now in exchange
    // for not mutating shared browser state from the analytics layer.
    const redactInterviewToken = (value: unknown): unknown =>
        typeof value === 'string' ? value.replace(/\/interview\/[^/?#]+/, '/interview/<redacted>') : value
    const URL_PROPERTIES = ['$current_url', '$pathname', '$referrer', '$initial_current_url', '$initial_pathname']
    posthog.setConfig({
        before_send: (event) => {
            if (event?.properties) {
                for (const key of URL_PROPERTIES) {
                    if (key in event.properties) {
                        event.properties[key] = redactInterviewToken(event.properties[key])
                    }
                }
            }
            return event
        },
    })
}
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
