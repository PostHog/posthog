import { KeaPlugin, resetContext } from 'kea'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'
import posthog from 'posthog-js'

import { isAccessDeniedError, shouldReportApiFailure } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import {
    addProjectIdIfMissing,
    ensureRoutablePathname,
    removeProjectIdIfPresent,
    stripTrailingSlash,
} from 'lib/utils/kea-router'
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
    'resolveFingerprint', // Retried while the error finishes ingesting; the fingerprint scene surfaces its own state
    'saveEarlyAccessFeature', // Field-level errors handled in earlyAccessFeatureLogic
    'loadWaitlistResponsesCount', // Soft-fails to a dash on the features list when survey access is missing
    'loadExistingSubscription', // Background eligibility check for the dashboard subscribe nudge
    'loadFreeTierSubscriptionCount', // Background free-tier limit check for the dashboard subscribe nudge
    'sendNudgeNotification', // Background delivery request for the dashboard subscribe nudge
    'loadDataset', // Dataset scenes render their own retry state
    'loadDatasetItems', // Dataset scenes render their own retry state
    'loadDatasetRevisions', // Dataset scenes render their own retry state
    'loadDatasetItemDetails', // Dataset item modals render their own retry state
    'loadDatasetItemVersions', // Dataset item modals render their own retry state
    'exportDataset', // Dataset scenes render their own retry state
    'generateSummary', // Summary view renders its own retry state
    'loadSelfDrivingEvaluationReports', // The self-driving eval table renders its own retry state
    'loadToolDataEvents',
    'loadInstallRequests', // Polled in the background on Settings → Integrations; the banner just stays hidden
    'loadPrChecks', // Polled in the Inbox report detail; the CI checks section renders its own error state
    'loadPrComments', // The Inbox report detail's PR comments section renders its own error state
    'loadMonitoringSnapshot', // The managed warehouse Monitoring tab renders its own retry state
    'loadMonitoringSeries', // The managed warehouse Monitoring tab renders its own partial/error state
]

/*
Write actions that show their own friendly message for access-denied 403s
(code `permission_denied`), so the generic toast would be a duplicate.
Unlike ERROR_FILTER_ALLOW_LIST, this only suppresses access-denied errors;
other failures on these actions still toast.
*/
const ACCESS_DENIED_SELF_HANDLED = new Set(['saveFeatureFlag'])

/*
Write actions whose own logic toasts the duplicate-key 400 (code `unique` on attr `key`), so the
generic toast would be a second one. Owned by featureFlagLogic's saveFeatureFlagFailure listener.
*/
const DUPLICATE_KEY_SELF_HANDLED = new Set(['saveFeatureFlag'])

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
                // Runs before kea-router's `decodeURI(pathname)` on every navigation (initial
                // load, push/replace, popstate). Keep the path decodable so a malformed `%`
                // routes to 404 instead of crashing the router.
                return addProjectIdIfMissing(ensureRoutablePathname(path))
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
                // Toast if it's a fetch error or a specific API update error
                const isLoadAction = typeof actionKey === 'string' && /^(load|get|fetch)[A-Z]/.test(actionKey)
                // Access-denied 403s (code `permission_denied`) are suppressed only where the
                // owning UI surfaces them itself: load actions (AccessDenied scene gates) and the
                // self-handled write actions above. Other writes keep the generic toast, since
                // most write flows have no failure handling of their own. Read-only impersonation
                // uses the distinct `impersonation_read_only` code and still toasts.
                const isAccessDenied =
                    isAccessDeniedError(error) && (isLoadAction || ACCESS_DENIED_SELF_HANDLED.has(String(actionKey)))
                if (
                    !ERROR_FILTER_ALLOW_LIST.includes(actionKey) &&
                    error?.status !== undefined &&
                    ![200, 201, 204, 401, 409].includes(error.status) && // 401 is handled by api.ts and the userLogic; 409 conflict flows surface their own UI
                    !(isLoadAction && error.status === 403) && // 403 access denied is handled by sceneLogic gates
                    !isAccessDenied
                ) {
                    let errorMessage = error.detail || error.statusText
                    const isTwoFactorError =
                        error.code === 'two_factor_setup_required' || error.code === 'two_factor_verification_required'
                    const isSensitiveActionError = error.code === 'sensitive_action_required_reauth'
                    // Only the 403 access-block gets the dedicated toast in apiStatusLogic; a 400
                    // with this code is form validation (e.g. inviting an outside-domain email)
                    // and must keep the generic error toast.
                    const isVerifiedDomainError = error.code === 'verified_domain_required' && error.status === 403
                    const isFeatureFlagDuplicateKey =
                        error.code === 'unique' &&
                        error.attr === 'key' &&
                        DUPLICATE_KEY_SELF_HANDLED.has(String(actionKey))

                    if (!errorMessage && error.status === 404) {
                        errorMessage = 'URL not found'
                    }
                    // Reword the default raw-seconds throttle detail via Retry-After; keep custom messages.
                    if (
                        error.status === 429 &&
                        typeof errorMessage === 'string' &&
                        errorMessage.startsWith('Request was throttled')
                    ) {
                        errorMessage = `Rate limit exceeded. Please try again ${error.formattedRetryAfter}.`
                    }
                    if (
                        isTwoFactorError ||
                        isSensitiveActionError ||
                        isVerifiedDomainError ||
                        isFeatureFlagDuplicateKey
                    ) {
                        // These are handled by their own dedicated toasts elsewhere.
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
                if (shouldReportApiFailure(error)) {
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
