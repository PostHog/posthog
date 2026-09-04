import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

/** A 403 with DRF's `permission_denied` code — the user lacks access to the resource itself. */
export function isAccessDeniedError(error: { status?: number; code?: string | null }): boolean {
    return error.status === 403 && error.code === 'permission_denied'
}

/**
 * A 409 from the approvals gate: the change was policy-gated and a change request was created,
 * or one is already pending. Approval 409 bodies always carry `change_request_id`
 * (see products/approvals/backend/decorators.py).
 */
export function isApprovalRequiredError(error: { status?: number; data?: any } | null | undefined): boolean {
    return error?.status === 409 && Boolean(error?.data?.change_request_id)
}

/** Infrastructure-level failures where the gateway couldn't reach the backend. */
const TRANSIENT_GATEWAY_STATUSES: ReadonlySet<number> = new Set([502, 503, 504])

function isTransientGatewayStatus(status: number | undefined): boolean {
    return status !== undefined && TRANSIENT_GATEWAY_STATUSES.has(status)
}

/**
 * A transient gateway failure (502/503/504) rather than anything the caller did wrong. These
 * often arrive with an empty body (so `detail` is null) and usually succeed on retry, so a
 * listener that has already shown a toast should stop here instead of rethrowing into
 * unhandled-rejection tracking. A plain 500 is excluded on purpose: it signals an application
 * bug, so it should keep surfacing its `detail` and reach error tracking.
 */
export function isTransientServerError(error: unknown): boolean {
    return error instanceof ApiError && isTransientGatewayStatus(error.status)
}

/** The 403 gates `apiStatusLogic` recovers from, keyed by the DRF `code` the backend sends. */
const HANDLED_AUTH_GATE_CODES: ReadonlySet<string> = new Set([
    'two_factor_setup_required',
    'two_factor_verification_required',
    'sensitive_action_required_reauth',
])

/**
 * How each browser engine words a `fetch` that never reached the server. Chromium says "Failed to
 * fetch", WebKit "Load failed", and Gecko "NetworkError when attempting to fetch resource.".
 */
export const BROWSER_FETCH_FAILURE_MESSAGES: readonly string[] = [
    'Failed to fetch',
    'Load failed',
    'NetworkError when attempting to fetch resource',
]

/**
 * A module the browser could not load, which is a defect of ours rather than connectivity: a chunk
 * an open tab still asks for went missing in a deploy. Chromium and Gecko word this by extending
 * one of the messages above, so a module failure has to be recognized before a connectivity one.
 *
 * `isChunkLoadError` answers a wider question, whether to retry the import or offer a reload, and
 * so it also treats a bare "Load failed" as a stale chunk. That guess is wrong for this decision,
 * because it would keep reporting every WebKit connectivity failure.
 */
const MODULE_LOAD_FAILURE_MESSAGES: readonly string[] = [
    'dynamically imported module',
    'Importing a module script failed',
]

/**
 * A `fetch` the browser refused to complete, recognized by the message the engine produced. The
 * request never reached the server, so there is no status to react to and no code path of ours to
 * fix: the cause is an ad blocker, tracking protection, DNS, a captive portal, or a connection that
 * dropped mid-request.
 *
 * The match is on the message and not on the `TypeError` class on purpose. Application bugs raise
 * status-less `TypeError`s too, such as "x is not a function", and dropping those would hide real
 * crashes.
 */
export function isBrowserNetworkFailure(error: unknown): boolean {
    if (error === null || typeof error !== 'object') {
        return false
    }
    const message = (error as { message?: unknown }).message
    if (typeof message !== 'string') {
        return false
    }
    if (MODULE_LOAD_FAILURE_MESSAGES.some((known) => message.includes(known))) {
        return false
    }
    return BROWSER_FETCH_FAILURE_MESSAGES.some((known) => message.includes(known))
}

/**
 * Whether a failed request is worth filing as an error tracking issue. A response the app asked
 * for and recovers from itself is not a defect, and reporting it buries the ones that are: every
 * `ApiError` is built in this file, so they all share one stack, and grouping ignores the message
 * once that stack resolves, which lands a handled 401 in the same issue as a genuine crash.
 *
 * Left unreported, because something else already resolves them for the user:
 * - 401 — an authentication state rather than a crash. `apiStatusLogic` re-checks the session and
 *   logs the user out, best-effort: it bails while impersonating (where `ImpersonationNotice`
 *   offers re-impersonation instead), before the user has loaded, and within 10s of its last check.
 * - 402 — a billing or entitlement state (a paygate or a quota limit), not an application bug. The
 *   paygate the request sits behind already tells the user how to upgrade.
 * - 403 `permission_denied` — the sceneLogic gates render the AccessDenied scene.
 * - 403 auth gates — `apiStatusLogic` opens 2FA setup, re-verification, or a re-auth prompt.
 * - 409 carrying a `change_request_id` — the approvals UI shows the change request it created.
 * - 502/503/504 — the gateway couldn't reach the backend, so application code is not at fault.
 *
 * Left unreported for a second reason, that there is nothing to fix:
 * - a `fetch` the browser never completed. No request reached us, so no code of ours failed, and
 *   the user is told by whatever the caller renders for an empty result. Reporting these is what
 *   floods the project: grouping is stack-based, so every loader that meets the same connectivity
 *   blip opens an issue of its own, and one bad minute on a user's network manufactures dozens.
 *
 * Each of these still toasts wherever it did before, and `client_request_failure` still records
 * every non-OK response with its status and pathname, so failure rates stay queryable even where
 * no recovery runs. That event is also the better record, since an exception raised here cannot say
 * which endpoint failed: every `ApiError` shares this file's stack.
 *
 * A plain 500 stays reportable on purpose, being a genuine backend exception. So does a status-less
 * failure that is not a recognized connectivity failure, such as a thrown string, a bare `Error`,
 * or an application `TypeError`, because there is no response to excuse it. A failed module import
 * keeps reporting too, since a stale chunk after a deploy is a defect we can fix.
 */
export function shouldReportApiFailure(error: unknown): boolean {
    if (isBrowserNetworkFailure(error)) {
        return false
    }
    if (error === null || typeof error !== 'object') {
        return true
    }
    const failure = error as { status?: number; code?: string | null; data?: any }
    const status = typeof failure.status === 'number' ? failure.status : undefined
    if (status === undefined) {
        return true
    }
    if (status === 401 || status === 402 || isTransientGatewayStatus(status)) {
        return false
    }
    if (isAccessDeniedError(failure)) {
        return false
    }
    if (status === 403 && failure.code != null && HANDLED_AUTH_GATE_CODES.has(failure.code)) {
        return false
    }
    return !isApprovalRequiredError(failure)
}

export class ApiError extends Error {
    /** Django REST Framework `detail` - used in downstream error handling. */
    detail: string | null
    /** Django REST Framework `code` - used in downstream error handling. */
    code: string | null
    /** Django REST Framework `statusText` - used in downstream error handling. */
    statusText: string | null
    /** Django REST Framework `attr` - used in downstream error handling. */
    attr: string | null

    /** Link to external resources, e.g. stripe invoices */
    link: string | null

    constructor(
        message?: string,
        public status?: number,
        public headers?: Headers,
        public data?: any
    ) {
        message = message || `API request failed with status: ${status ?? 'unknown'}`
        super(message)
        this.statusText = data?.statusText || null
        this.detail = data?.detail || null
        this.code = data?.code || null
        this.link = data?.link || null
        this.attr = data?.attr || null
    }

    static async fromResponse(response: Response, fallbackMessage?: string): Promise<ApiError> {
        let data: unknown = null

        try {
            data = await response.json()
        } catch (error) {
            if ((error as { name?: string } | null)?.name === 'AbortError') {
                throw error
            }
        }

        const errorData = data && typeof data === 'object' ? (data as Record<string, unknown>) : null
        const responseMessage = [errorData?.error, errorData?.detail, errorData?.message].find(
            (value): value is string => typeof value === 'string'
        )

        return new ApiError(responseMessage || fallbackMessage, response.status, response.headers, data)
    }

    /**
     * For when the API returned a 429 (Too Many Requests) error:
     * If the `Retry-After` header is present, return a human-friendly duration, e.g. "in 4 hours", otherwise just "later".
     * Return null for other status codes.
     */
    get formattedRetryAfter(): string | null {
        if (this.status !== 429) {
            return null
        }
        if (this.headers?.has('Retry-After')) {
            const retryAfter = this.headers.get('Retry-After') as string
            let secondsLeft = Number(retryAfter) // Let's assume we're dealing with an integer by default
            if (isNaN(secondsLeft)) {
                // Nope, here we're dealing with date in this format: Wed, 21 Oct 2015 07:28:00 GMT
                secondsLeft = dayjs(retryAfter).diff(dayjs(), 'seconds')
            }
            return `in ${humanFriendlyDuration(secondsLeft, { maxUnits: 2 })}`
        }
        return 'later'
    }
}

/**
 * Why a request never reached the server. `offline` and `navigating` describe the state of the
 * client rather than a fault in the request path, so they are dropped before they reach error
 * tracking (see `dropUnactionableNetworkExceptions`). `network` is the residue that is worth
 * looking at: an ad blocker, a misconfigured reverse proxy, DNS, a CDN, or our own edge.
 */
export type NetworkFailureReason = 'offline' | 'navigating' | 'network'

/**
 * One fixed message per reason. Two constraints meet here. The browser's own wording varies by
 * engine ("Failed to fetch", "Load failed", "NetworkError when attempting to fetch resource."),
 * and the automatic unhandled-rejection capture carries no custom properties, so the message is
 * the only place the reason can travel to `before_send` and to error tracking grouping rules.
 */
export const NETWORK_ERROR_MESSAGES = {
    offline: 'Network request failed: device is offline',
    navigating: 'Network request failed: page was closing',
    network: 'Network request failed',
} as const satisfies Record<NetworkFailureReason, string>

/** The reasons that are never a defect, so filing them as error tracking issues only adds noise. */
export const UNACTIONABLE_NETWORK_ERROR_MESSAGES: ReadonlySet<string> = new Set([
    NETWORK_ERROR_MESSAGES.offline,
    NETWORK_ERROR_MESSAGES.navigating,
])

/**
 * A request the browser never completed, so there is no HTTP status to react to. `status` is left
 * undefined on purpose: recovery paths across the app read `status === undefined` as "transient,
 * may be retried" (for example `inviteSignupLogic` and `sourcesDataLogic`), and a placeholder like
 * 0 would make them treat a connectivity blip as a client error.
 */
export class NetworkError extends ApiError {
    constructor(
        public reason: NetworkFailureReason,
        cause?: unknown
    ) {
        super(NETWORK_ERROR_MESSAGES[reason])
        // Sets the `type` posthog-js reports in `$exception_list`, which is what
        // `dropUnactionableNetworkExceptions` and error tracking grouping rules match on.
        this.name = 'NetworkError'
        this.cause = cause
    }
}
