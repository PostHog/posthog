import '~/styles'

import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import { getContext } from 'kea'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'
import { createRoot } from 'react-dom/client'

import { App } from 'scenes/App'

import './buffer-polyfill'
import { initKea } from './initKea'
import { ErrorBoundary } from './layout/ErrorBoundary'
import { loadPostHogJS } from './loadPostHogJS'

loadPostHogJS()
initKea()

// On Chrome + Windows, the country flag emojis don't render correctly. This is a polyfill for that.
// It won't be applied on other platforms.
//
// NOTE: The first argument is the name of the polyfill to use. This is used to set the font family in our CSS.
// Make sure to update the font family in the CSS if you change this.
polyfillCountryFlagEmojis('Emoji Flags Polyfill')

// Expose `window.getReduxState()` to make snapshots to storybook easy
if (typeof window !== 'undefined') {
    // Disabled in production to prevent leaking secret data, personal API keys, etc
    if (process.env.NODE_ENV === 'development') {
        ;(window as any).getReduxState = () => getContext().store.getState()
    } else {
        ;(window as any).getReduxState = () => 'Disabled outside development!'
    }
}

function renderApp(): void {
    const root = document.getElementById('root')
    if (root) {
        createRoot(root).render(
            <ErrorBoundary>
                <PostHogProvider client={posthog}>
                    <App />
                </PostHogProvider>
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
