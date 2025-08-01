import { KeaPlugin, resetContext } from 'kea'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { identifierToHuman } from 'lib/utils'
import { addProjectIdIfMissing, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import posthog from 'posthog-js'
import { sceneTabsLogic } from '~/layout/scenes/sceneTabsLogic'

/*
Actions for which we don't want to show error alerts,
mostly to avoid user confusion.
*/
const ERROR_FILTER_ALLOW_LIST = [
    'loadPreflight', // Gracefully handled if it fails
    'loadUser', // App won't load (unless loading from shared dashboards)
    'loadFunnels', // Special error handling on insights
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
    replaceInitialPathInWindow?: boolean
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

export function initKea({
    routerHistory,
    routerLocation,
    beforePlugins,
    replaceInitialPathInWindow,
}: InitKeaProps = {}): void {
    const plugins = [
        ...(beforePlugins || []),
        localStoragePlugin(),
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
            replaceInitialPathInWindow:
                typeof replaceInitialPathInWindow === 'undefined' ? true : replaceInitialPathInWindow,
            getRouterState: () => {
                // This state is persisted into window.history
                const logic = sceneTabsLogic.findMounted()
                if (logic) {
                    return { tabs: structuredClone(logic.values.tabs) }
                }
                return undefined
            },
        }),
        formsPlugin,
        loadersPlugin({
            onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                // Toast if it's a fetch error or a specific API update error
                if (
                    !ERROR_FILTER_ALLOW_LIST.includes(actionKey) &&
                    error?.status !== undefined &&
                    ![200, 201, 204, 401].includes(error.status)
                    // 401 is handled by api.ts and the userLogic
                ) {
                    let errorMessage = error.detail || error.statusText

                    if (!errorMessage && error.status === 404) {
                        errorMessage = 'URL not found'
                    }
                    if (errorMessage) {
                        lemonToast.error(`${identifierToHuman(actionKey)} failed: ${errorMessage}`)
                    }
                }
                if (!errorsSilenced) {
                    console.error({ error, reducerKey, actionKey })
                }
                posthog.captureException(error)
            },
        }),
        subscriptionsPlugin,
        waitForPlugin,
    ]

    // To enable logging, run localStorage.setItem("ph-kea-debug", true) in the console
    if (window.JS_KEA_VERBOSE_LOGGING || ('localStorage' in window && window.localStorage.getItem('ph-kea-debug'))) {
        plugins.push(loggerPlugin)
    }

    if ((window as any).__REDUX_DEVTOOLS_EXTENSION__) {
        // eslint-disable-next-line no-console
        console.log('NB Redux Dev Tools are disabled on PostHog. See: https://github.com/PostHog/posthog/issues/17482')
    }

    resetContext({
        plugins: plugins,
        createStore: {
            // Disable redux dev-tools's compose by passing `compose` from redux directly
            compose: ((...funcs: any[]) => {
                if (funcs.length === 0) {
                    return <T>(arg: T) => arg
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
