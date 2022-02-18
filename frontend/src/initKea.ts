import { KeaPlugin, resetContext } from 'kea'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { loadersPlugin } from 'kea-loaders'
import { windowValuesPlugin } from 'kea-window-values'
import { errorToast, identifierToHuman } from 'lib/utils'
import { waitForPlugin } from 'kea-waitfor'

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

export function initKea({ state, routerHistory, routerLocation, beforePlugins }: InitKeaProps = {}): void {
    resetContext({
        plugins: [
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
            loadersPlugin({
                onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                    // Toast if it's a fetch error or a specific API update error
                    if (
                        !ERROR_FILTER_WHITELIST.includes(actionKey) &&
                        (error?.message === 'Failed to fetch' || // Likely CORS headers errors (i.e. request failing without reaching Django)
                            (error?.status !== undefined && ![200, 201, 204].includes(error.status)))
                    ) {
                        errorToast(
                            `Error on ${identifierToHuman(reducerKey)}`,
                            `Attempting to ${identifierToHuman(actionKey).toLowerCase()} returned an error:`,
                            error.status !== 0
                                ? error.detail
                                : "Check your internet connection and make sure you don't have an extension blocking our requests.",
                            error.code
                        )
                    }
                    if (!errorsSilenced) {
                        console.error(error)
                    }
                    ;(window as any).Sentry?.captureException(error)
                },
            }),
            waitForPlugin,
        ],
        defaults: state,
        createStore: state
            ? {
                  preloadedState: state,
              }
            : true,
    })
}
