import { KeaPlugin, resetContext } from 'kea'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'
import { windowValuesPlugin } from 'kea-window-values'
import { identifierToHuman } from 'lib/utils'
import { waitForPlugin } from 'kea-waitfor'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { formsPlugin } from 'kea-forms'

/*
Actions for which we don't want to show error alerts,
mostly to avoid user confusion.
*/
const ERROR_FILTER_WHITELIST = [
    'loadPreflight', // Gracefully handled if it fails
    'loadUser', // App won't load (unless loading from shared dashboards)
    'loadFunnels', // Special error handling on insights
    'loadResults', // Special error handling on insights
    'authenticate', // Special error handling on login
    'signup', // Special error handling on login
    'loadLatestVersion',
    'loadBilling', // Gracefully handled if it fails
    'loadData', // Gracefully handled in the data table
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
                console.groupCollapsed('KEA LOGGER', action)
                console.log(store.getState())
                console.groupEnd()
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
                // :TRICKY: We override default url segment matching characters.
                // This list includes all characters which are not escaped by encodeURIComponent
                segmentValueCharset: "a-zA-Z0-9-_~ %.@()!'",
            },
        }),
        formsPlugin,
        loadersPlugin({
            onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                // Toast if it's a fetch error or a specific API update error
                if (
                    !ERROR_FILTER_WHITELIST.includes(actionKey) &&
                    (error?.message === 'Failed to fetch' || // Likely CORS headers errors (i.e. request failing without reaching Django)
                        (error?.status !== undefined && ![200, 201, 204].includes(error.status)))
                ) {
                    lemonToast.error(
                        `${identifierToHuman(actionKey)} failed: ${
                            error.detail || error.statusText || 'PostHog may be offline'
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
