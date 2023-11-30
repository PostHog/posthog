import { KeaPlugin, resetContext } from 'kea'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { identifierToHuman } from 'lib/utils'

/*
Actions for which we don't want to show error alerts,
mostly to avoid user confusion.
*/
const ERROR_FILTER_ALLOW_LIST = [
    'loadPreflight', // Gracefully handled if it fails
    'loadUser', // App won't load (unless loading from shared dashboards)
    'loadFunnels', // Special error handling on insights
    'loadResults', // Special error handling on insights
    'authenticate', // Special error handling on login
    'signup', // Special error handling on login
    'loadLatestVersion',
    'loadBilling', // Gracefully handled if it fails
    'loadData', // Gracefully handled in the data table
    'loadRecordingMeta', // Gracefully handled in the recording player
]

interface InitKeaProps {
    state?: Record<string, any>
    routerHistory?: any
    routerLocation?: any
    beforePlugins?: KeaPlugin[]
}

// Used in some tests to make life easier
let errorsSilenced = false

export function silenceKeaLoadersErrors(): void {
    errorsSilenced = true
}

export function resumeKeaLoadersErrors(): void {
    errorsSilenced = false
}

export const loggerPlugin: () => KeaPlugin = () => ({
    name: 'verbose-kea-logger',
    events: {
        beforeReduxStore(options) {
            options.middleware.push((store) => (next) => (action) => {
                const response = next(action)
                /* eslint-disable no-console */
                console.groupCollapsed('KEA LOGGER', action)
                console.log(store.getState())
                console.groupEnd()
                /* eslint-enable no-console */
                return response
            })
        },
    },
})

export function initKea({ routerHistory, routerLocation, beforePlugins }: InitKeaProps = {}): void {
    const plugins = [
        ...(beforePlugins || []),
        localStoragePlugin,
        windowValuesPlugin({ window: window }),
        routerPlugin({
            history: routerHistory,
            location: routerLocation,
            urlPatternOptions: {
                // :TRICKY: What chars to allow in named segment values i.e. ":key"
                // in "/url/:key". Default: "a-zA-Z0-9-_~ %".
                segmentValueCharset: "a-zA-Z0-9-_~ %.@()!'|",
            },
        }),
        formsPlugin,
        loadersPlugin({
            onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                // Toast if it's a fetch error or a specific API update error
                if (
                    !ERROR_FILTER_ALLOW_LIST.includes(actionKey) &&
                    (error?.message === 'Failed to fetch' || // Likely CORS headers errors (i.e. request failing without reaching Django)
                        (error?.status !== undefined && ![200, 201, 204].includes(error.status)))
                ) {
                    let errorMessageFallback = 'PostHog may be offline'
                    if (error.status === 404) {
                        errorMessageFallback = 'URL not found'
                    }
                    lemonToast.error(
                        `${identifierToHuman(actionKey)} failed: ${
                            error.detail || error.statusText || errorMessageFallback
                        }`
                    )
                }
                if (!errorsSilenced) {
                    console.error({ error, reducerKey, actionKey })
                }
                ;(window as any).Sentry?.captureException(error)
            },
        }),
        subscriptionsPlugin,
        waitForPlugin,
    ]

    if (window.JS_KEA_VERBOSE_LOGGING) {
        plugins.push(loggerPlugin)
    }

    resetContext({
        plugins: plugins,
    })
}
