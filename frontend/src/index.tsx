// Add the beginning of your app entry - required for Vite backend integration
import 'vite/modulepreload-polyfill'

import '~/styles'

import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import { getContext, resetContext } from 'kea'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'
import { createRoot } from 'react-dom/client'
import { App } from 'scenes/App'

// import { initKea } from './initKea'
// import { ErrorBoundary } from './layout/ErrorBoundary'
// import { loadPostHogJS } from './loadPostHogJS'

// Minimal PostHog loader to avoid circular dependencies
function loadPostHogJS(): void {
    if ((window as any).JS_POSTHOG_API_KEY) {
        posthog.init((window as any).JS_POSTHOG_API_KEY, {
            opt_out_useragent_filter: window.location.hostname === 'localhost',
            api_host: (window as any).JS_POSTHOG_HOST,
            ui_host: (window as any).JS_POSTHOG_UI_HOST,
            rageclick: true,
            persistence: 'localStorage+cookie',
            bootstrap: (window as any).POSTHOG_USER_IDENTITY_WITH_FLAGS ? (window as any).POSTHOG_USER_IDENTITY_WITH_FLAGS : {},
            opt_in_site_apps: true,
            api_transport: 'fetch',
            loaded: (loadedInstance) => {
                if (loadedInstance.sessionRecording) {
                    loadedInstance.sessionRecording._forceAllowLocalhostNetworkCapture = true
                }

                if ((window as any).IMPERSONATED_SESSION) {
                    loadedInstance.sessionManager?.resetSessionId()
                    loadedInstance.opt_out_capturing()
                } else {
                    loadedInstance.opt_in_capturing()
                }

                (window as any).posthog = loadedInstance
            },
            scroll_root_selector: ['main', 'html'],
            autocapture: {
                capture_copied_text: true,
            },
            capture_performance: { web_vitals: true },
            person_profiles: 'always',
            __preview_remote_config: true,
            __preview_flags_v2: true,
        })
    } else {
        posthog.init('fake token', {
            autocapture: false,
            loaded: function (ph) {
                ph.opt_out_capturing()
            },
        })
    }
}

// Minimal initKea function to avoid circular dependencies
function initKea(): void {
    const plugins = [
        localStoragePlugin(),
        windowValuesPlugin({ window: window }),
        routerPlugin({
            urlPatternOptions: {
                segmentValueCharset: "a-zA-Z0-9-_~ %.@()!'|",
            },
        }),
        formsPlugin,
        loadersPlugin({
            onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                console.error({ error, reducerKey, actionKey })
                posthog.captureException?.(error)
            },
        }),
        subscriptionsPlugin,
        waitForPlugin,
    ]

    resetContext({
        plugins: plugins,
        createStore: {
            compose: ((...funcs: any[]) => {
                if (funcs.length === 0) {
                    return (arg: any) => arg
                }
                if (funcs.length === 1) {
                    return funcs[0]
                }
                return funcs.reduce(
                    (a, b) =>
                        (...args: any) =>
                            a(b(...args))
                )
            }) as any,
        },
    })
}

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
            <PostHogProvider client={posthog}>
                <App />
            </PostHogProvider>
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
