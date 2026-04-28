import { KeaPlugin, resetContext } from 'kea'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { identifierToHuman } from 'lib/utils'
import { addProjectIdIfMissing, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { getTabsSnapshotForHistory, sceneLogic } from 'scenes/sceneLogic'

import { disposablesPlugin } from '~/kea-disposables'

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
    'loadSimilarIssues', // Gracefully handled in the similar issues list
    'saveEarlyAccessFeature', // Field-level errors handled in earlyAccessFeatureLogic
]

interface InitKeaProps {
    state?: Record<string, any>
    routerHistory?: any
    routerLocation?: any
    beforePlugins?: KeaPlugin[]
    replaceInitialPathInWindow?: boolean
}

// Break kea logic graph cycles after unmount so unmounted BuiltLogic
// instances don't transitively retain the rest of the graph if some external
// closure still holds them.
//
// kea v4's `unmountLogic` removes a built logic from `mounted`, `counter`,
// and `wrapperContexts.builtLogics`, but does NOT clear the BuiltLogic
// object's own `connections`, `events`, `listeners`, `selectors`, etc. Each
// logic's `connections` map points at every transitively connected logic, so
// once any single unmounted BuiltLogic is rooted from outside (e.g. by a
// React fiber alternate, a redux middleware closure, or a stale Monaco model
// ref), the entire connected graph stays alive.
//
// Heap-snapshot diffs on /sql showed 5 BuiltLogic instances per visit for
// every connected logic, including singletons. Nulling these fields on
// afterUnmount caps the leak at the empty BuiltLogic shell.
//
// Safe because kea doesn't guarantee post-unmount logic access. `isMounted()`
// lives in the BuiltLogic's closure (not in a data field) and continues to
// work. Plugins that need `logic.cache` etc. read it in `beforeUnmount`,
// which runs before this `afterUnmount`.
const cycleBreakerPlugin: KeaPlugin = {
    name: 'cycleBreaker',
    events: {
        afterUnmount(logic) {
            const l = logic as any
            // Clear the heavy closure-bearing fields synchronously. These
            // are what retain reselect machinery, listener bodies, and
            // propsChanged/beforeUnmount2 closures that hold an unmounted
            // BuiltLogic alive when any external closure still references it.
            l.events = {}
            l.listeners = {}

            // Defer clearing `connections` to the next macrotask. kea v4's
            // `unmountLogic` reads `logic.connections[pathString]` and
            // `connectedLogic.events.beforeUnmount?.()` per iteration. After
            // `.reverse()` the outer logic is unmounted first, so clearing
            // its `connections` synchronously makes subsequent iterations
            // dereference `undefined.events` and crash.
            //
            // setTimeout(0) waits until kea's full unmount sweep completes.
            // We don't gate on `isMounted()` because that checks the counter
            // for `pathString`, which can be true again if a fresh build at
            // the same path was mounted in the interim — but that's a
            // DIFFERENT BuiltLogic instance with its own `connections` map,
            // so clearing this stale instance's `connections` is safe.
            setTimeout(() => {
                l.connections = {}
            }, 0)
        },
    },
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
        disposablesPlugin,
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
                    // Strip sceneParams etc. — they are not JSON-safe and break structuredClone (cyclic/deep graphs)
                    const tabs = getTabsSnapshotForHistory(logic.values.tabs)
                    if (typeof structuredClone !== 'undefined') {
                        return { tabs: structuredClone(tabs) }
                    }
                    // structuredClone fails in jest for some reason, despite us being on the right versions
                    return { tabs: JSON.parse(JSON.stringify(tabs)) || [] }
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
                    ![200, 201, 204, 401, 409].includes(error.status) && // 401 is handled by api.ts and the userLogic, 409 is handled by approval workflow
                    !(isLoadAction && error.status === 403) // 403 access denied is handled by sceneLogic gates
                ) {
                    let errorMessage = error.detail || error.statusText
                    const isTwoFactorError =
                        error.code === 'two_factor_setup_required' || error.code === 'two_factor_verification_required'
                    const isSensitiveActionError = error.code === 'sensitive_action_required_reauth'

                    if (!errorMessage && error.status === 404) {
                        errorMessage = 'URL not found'
                    }
                    if (isTwoFactorError || isSensitiveActionError) {
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
        // Must be appended LAST so its afterUnmount runs after every other
        // plugin and the user-provided beforeUnmount/afterUnmount events have
        // had a chance to read logic.cache, logic.events, etc.
        cycleBreakerPlugin,
    ]

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
