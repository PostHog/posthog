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
import { addProjectIdIfMissing, removeProjectIdIfPresent, stripTrailingSlash } from 'lib/utils/kea-router'
import { identifierToHuman } from 'lib/utils/strings'

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

/*
Transient gateway/proxy errors. These are infrastructure-level failures (the gateway can't
reach the backend), not application bugs, so we still toast the user a retryable failure but
don't report them to error tracking — otherwise sporadic 5xxs surface as noisy code-regression
issues. 500 is intentionally excluded: those are genuine backend exceptions worth capturing.
*/
const TRANSIENT_GATEWAY_STATUSES = [502, 503, 504]

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
                return stripTrailingSlash(removeProjectIdIfPresent(path))
            },
            replaceInitialPathInWindow:
                typeof replaceInitialPathInWindow === 'undefined' ? true : replaceInitialPathInWindow,
        }),
        formsPlugin,
        loadersPlugin({
            onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                // A request aborted by us (superseded query, unmount, manual cancel) is not a
                // failure — don't toast, log, or report it.
                if (error?.name === 'AbortError') {
                    return
                }
                // Read-only mode (`ReadOnlyModeError`) flows through this path unchanged:
                // it extends `ApiError` with `status=403`, so the `!(isLoadAction && error.status === 403)`
                // condition already suppresses the toast for load actions, and write actions
                // get a toast with the read-only `detail` as the message. The
                // `posthog.captureException` event is dropped by the central
                // `before_send` filter in `selfReadOnlyModeLogic`.
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
                // Cooperative cancellation (an aborted fetch, or a query superseded via
                // `abortController.abort('new query started')` as in the logs/tracing data
                // logics) is expected control flow, not a failure worth logging or reporting.
                const isCancellation =
                    error?.name === 'AbortError' ||
                    error === 'new query started' ||
                    error?.message === 'new query started'
                if (isCancellation) {
                    return
                }
                if (!errorsSilenced) {
                    console.error({ error, reducerKey, actionKey })
                }
                if (!TRANSIENT_GATEWAY_STATUSES.includes(error?.status)) {
                    posthog.captureException(error)
                }
            },
        }),
        subscriptionsPlugin,
        waitForPlugin,
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
