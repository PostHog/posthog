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
import { getCurrentTeamId } from 'lib/utils/logics'

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

export function pathsWithoutProjectId(path: string): boolean {
    return !!(
        path.match(/^\/me\//) ||
        path.match(/^\/instance\//) ||
        path.match(/^\/organization\//) ||
        path.match(/^\/preflight/) ||
        path.match(/^\/login/) ||
        path.match(/^\/signup/)
    )
}

export function addProjectIdUnlessPresent(path: string, teamId?: number): string {
    let prefix = ''
    try {
        if (teamId) {
            prefix = `/project/${teamId}`
        } else {
            prefix = `/project/${getCurrentTeamId()}`
        }
        if (path == '/') {
            return prefix
        }
    } catch (e) {
        // Not logged in
    }
    if (path === prefix || path.startsWith(prefix + '/')) {
        return path
    }
    return `${prefix}/${path.startsWith('/') ? path.slice(1) : path}`
}

export function removeProjectIdIfPresent(path: string): string {
    if (path.match(/^\/project\/\d+/)) {
        return '/' + path.split('/').splice(3).join('/')
    }
    return path
}

export function addProjectIdIfMissing(path: string, teamId?: number): string {
    return pathsWithoutProjectId(path) ? removeProjectIdIfPresent(path) : addProjectIdUnlessPresent(path, teamId)
}

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
            pathFromRoutesToWindow: (path) => {
                return addProjectIdIfMissing(path)
            },
            transformPathInActions: (path) => {
                return addProjectIdIfMissing(path)
            },
            pathFromWindowToRoutes: (path) => {
                return removeProjectIdIfPresent(path)
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
