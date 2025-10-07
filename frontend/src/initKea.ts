import { KeaPlugin, resetContext } from 'kea'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'
import posthog, { PostHog } from 'posthog-js'
import { posthogKeaLogger, sessionRecordingLoggerForPostHogInstance } from 'posthog-js/lib/src/customizations'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { hashCodeForString, identifierToHuman } from 'lib/utils'
import { addProjectIdIfMissing, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sceneLogic } from 'scenes/sceneLogic'

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
                segmentValueCharset: "a-zA-Z0-9-_~ %.@()!'|:",
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
                const logic = sceneLogic.findMounted()
                if (logic) {
                    if (typeof structuredClone !== 'undefined') {
                        return { tabs: structuredClone(logic.values.tabs) }
                    }
                    // structuredClone fails in jest for some reason, despite us being on the right versions
                    return { tabs: JSON.parse(JSON.stringify(logic.values.tabs)) || [] }
                }
                return undefined
            },
        }),
        formsPlugin,
        loadersPlugin({
            onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                // Toast if it's a fetch error or a specific API update error
                const isLoadAction = typeof actionKey === 'string' && /^(load|get|fetch)[A-Z]/.test(actionKey)
                if (
                    !ERROR_FILTER_ALLOW_LIST.includes(actionKey) &&
                    error?.status !== undefined &&
                    ![200, 201, 204, 401].includes(error.status) && // 401 is handled by api.ts and the userLogic
                    !(isLoadAction && error.status === 403) // 403 access denied is handled by sceneLogic gates
                ) {
                    let errorMessage = error.detail || error.statusText
                    const isTwoFactorError =
                        error.code === 'two_factor_setup_required' || error.code === 'two_factor_verification_required'

                    if (!errorMessage && error.status === 404) {
                        errorMessage = 'URL not found'
                    }
                    if (isTwoFactorError) {
                        errorMessage = null
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

    if (window.APP_STATE_LOGGING_SAMPLE_RATE) {
        try {
            const ph: PostHog | undefined = window.posthog
            const session_id = ph?.get_session_id()
            const sample_rate = parseFloat(window.APP_STATE_LOGGING_SAMPLE_RATE)
            if (session_id) {
                const sessionIdHash = hashCodeForString(session_id)
                if (sessionIdHash % 100 < sample_rate * 100) {
                    window.JS_KEA_VERBOSE_LOGGING = true
                }
            }
        } catch (e) {
            window.posthog.captureException(e)
        }
    }
    // To enable logging, run localStorage.setItem("ph-kea-debug", true) in the console
    // to explicitly disable the logging, run localStorage.setItem("ph-kea-debug", false)
    const localStorageLoggingFlag = 'localStorage' in window && window.localStorage.getItem('ph-kea-debug')
    const localStorageDisablesLogging = localStorageLoggingFlag === 'false'
    const localStorageEnablesLogging = localStorageLoggingFlag === 'true'
    if (!localStorageDisablesLogging && (localStorageEnablesLogging || window.JS_KEA_VERBOSE_LOGGING)) {
        plugins.push(
            posthogKeaLogger({
                logger: sessionRecordingLoggerForPostHogInstance(window.posthog),
            })
        )
    }

    if ((window as any).__REDUX_DEVTOOLS_EXTENSION__) {
        // oxlint-disable-next-line no-console
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
