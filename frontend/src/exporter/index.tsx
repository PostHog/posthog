import '~/styles'

import './Exporter.scss'

import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import { createRoot } from 'react-dom/client'

import api, { ApiConfig } from 'lib/api'
import { getAppContext } from 'lib/utils/getAppContext'
import { Exporter } from '~/exporter/Exporter'
import { ExportType, ExportedData } from '~/exporter/types'
import { initKea } from '~/initKea'
import { loadPostHogJS } from '~/loadPostHogJS'

import { ErrorBoundary } from '../layout/ErrorBoundary'

// Disable tracking for all exports and embeds.
// This is explicitly set as to not track our customers' customers data.
// Without it, embeds of self-hosted iframes will log metrics to app.posthog.com.
window.JS_POSTHOG_API_KEY = undefined

loadPostHogJS()
initKea({ replaceInitialPathInWindow: false })

// Initialize ApiConfig from app context for image exports
// This must happen synchronously before any logic tries to use it
const exportedData: ExportedData = window.POSTHOG_EXPORTED_DATA
if (exportedData?.type === ExportType.Image) {
    const appContext = getAppContext()
    if (appContext?.current_team?.id) {
        ApiConfig.setCurrentTeamId(appContext.current_team.id)
        // For image exports, use team ID as project ID (backend sets current_project to None)
        ApiConfig.setCurrentProjectId(appContext.current_team.id)
    }
    if (appContext?.current_team?.organization) {
        ApiConfig.setCurrentOrganizationId(appContext.current_team.organization)
    }
}

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
