import '~/styles'

import './Exporter.scss'

import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import { createRoot } from 'react-dom/client'

import { Exporter } from '~/exporter/Exporter'
import { ExporterLogin } from '~/exporter/ExporterLogin'
import { ExportedData } from '~/exporter/types'
import { initKea } from '~/initKea'
import { ApiConfig } from '~/lib/api'
import { loadPostHogJS } from '~/loadPostHogJS'

import { ErrorBoundary } from '../layout/ErrorBoundary'

// Disable tracking for all exports and embeds.
// This is explicitly set as to not track our customers' customers data.
// Without it, embeds of self-hosted iframes will log metrics to app.posthog.com.
window.JS_POSTHOG_API_KEY = undefined

loadPostHogJS()
initKea()

// Initialize API configuration if team context is available
if (window.POSTHOG_APP_CONTEXT?.current_team) {
    const team = window.POSTHOG_APP_CONTEXT.current_team

    ApiConfig.setCurrentTeamId(team.id)
    ApiConfig.setCurrentProjectId(team.project_id)

    // Also set organization ID if available (needed for some API calls)
    if (window.POSTHOG_APP_CONTEXT.current_user?.organization?.id) {
        ApiConfig.setCurrentOrganizationId(window.POSTHOG_APP_CONTEXT.current_user.organization.id)
    }
} else {
    // For password-protected shares, team context won't be available initially
    // It will be set after authentication via JWT
    console.warn('POSTHOG_APP_CONTEXT.current_team not available at exporter initialization')
    console.warn('API calls will fail until team context is set via authentication')
}

// On Chrome + Windows, the country flag emojis don't render correctly. This is a polyfill for that.
// It won't be applied on other platforms.
//
// NOTE: The first argument is the name of the polyfill to use. This is used to set the font family in our CSS.
// Make sure to update the font family in the CSS if you change this.
polyfillCountryFlagEmojis('Emoji Flags Polyfill')

const exportedData: ExportedData = window.POSTHOG_EXPORTED_DATA

function renderApp(): void {
    const root = document.getElementById('root')
    if (root) {
        createRoot(root).render(
            <ErrorBoundary>
                {exportedData.type === 'unlock' ? (
                    <ExporterLogin whitelabel={exportedData.whitelabel} />
                ) : (
                    <Exporter {...exportedData} />
                )}
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
