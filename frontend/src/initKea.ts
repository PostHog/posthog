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
// and `wrapperContexts.builtLogics`, but the `BuiltLogic` object's own
// `connections`, `events`, and `listeners` fields stay populated. The
// `connections` map points at every transitively connected logic, so once
// any single unmounted `BuiltLogic` is rooted from outside (e.g. by a React
// fiber alternate, a redux middleware closure, or a stale Monaco model ref),
// the whole connected graph stays alive.
//
// Heap-snapshot diffs on /sql showed 5 BuiltLogic instances per visit for
// every connected logic, including singletons. Nulling these three fields
// on afterUnmount caps the leak at the empty BuiltLogic shell. We only clear
// these three because heap diffs show they hold the bulk of the retention;
// `selectors` and `cache` are intentionally left alone — `cache.disposables`
// is managed by `disposablesPlugin.beforeUnmount`, and selector closures
// haven't been observed as a primary retainer once `connections` is gone.
//
// All three fields are cleared on the next macrotask via `setTimeout(0)`,
// not synchronously. Two reasons:
//
// 1. kea v4's `unmountLogic` reads `logic.connections[pathString]` and
//    `connectedLogic.events.beforeUnmount?.()` / `events.afterUnmount?.()`
//    per iteration. After `.reverse()` the outer logic is unmounted first,
//    so clearing its `connections` synchronously makes subsequent iterations
//    dereference `undefined.events` and crash.
//
// 2. Test patterns that `mount(); unmount(); mount();` on the same captured
//    BuiltLogic reference (e.g. `saveToDatasetButtonLogic.test.ts:476-489`)
//    rely on the logic still having its `connections`/`events`/`listeners`
//    populated for the second mount to actually wire anything up.
//    `mountLogic` walks `Object.keys(logic.connections)` — empty connections
//    means nothing mounts.
//
// `setTimeout(0)` waits until the current task fully unwinds, so kea
// finishes its sweep AND any synchronous remount completes against a
// populated graph. Cleanup still runs once the JS engine is idle, freeing
// the unmounted BuiltLogic's closure web.
//
// `isMounted()` lives in the BuiltLogic's closure (not in a data field) and
// continues to work. Plugins that need `logic.cache` etc. read it in
// `beforeUnmount`, which runs before this `afterUnmount`. `cache.disposables`
// is managed by `disposablesPlugin.beforeUnmount`; selectors aren't cleared
// because they haven't been observed as a primary retainer once
// `connections` is gone.
type MutableBuiltLogic = {
    events: Record<string, unknown>
    listeners: Record<string, unknown>
    connections: Record<string, unknown>
}

const postUnmountCleanupPlugin: KeaPlugin = {
    name: 'postUnmountCleanup',
    events: {
        afterUnmount(logic) {
            const l = logic as unknown as MutableBuiltLogic

            // No-op if `setTimeout` isn't available (e.g. SSR). The cleanup
            // is purely a memory optimisation; missing it doesn't break
            // correctness.
            if (typeof setTimeout !== 'function') {
                return
            }
            setTimeout(() => {
                l.events = {}
                l.listeners = {}
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
        postUnmountCleanupPlugin,
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
