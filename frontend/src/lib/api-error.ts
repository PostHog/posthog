import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

/** A 403 with DRF's `permission_denied` code — the user lacks access to the resource itself. */
export function isAccessDeniedError(error: { status?: number; code?: string | null }): boolean {
    return error.status === 403 && error.code === 'permission_denied'
}

/*
403 codes where the backend is enforcing an authorization rule and the app already answers it —
an access-denied gate, the 2FA setup modal, the re-authentication prompt. The status is scoped to
403 deliberately: the same code on a 400 is form validation and still worth reporting.
*/
const EXPECTED_AUTHORIZATION_CODES = new Set([
    'permission_denied',
    'two_factor_setup_required',
    'two_factor_verification_required',
    'sensitive_action_required_reauth',
    'verified_domain_required',
])

/**
 * A 403 the app expects and handles, so error tracking should ignore it. One blocked page load
 * fails every request the app makes on boot, and each call site fingerprints as its own issue —
 * enough volume to bury real frontend errors.
 */
export function isExpectedAuthorizationError(error: unknown): boolean {
    // Takes `unknown` because every call site is a catch block or kea's untyped loader error.
    const { status, code } = (error ?? {}) as { status?: number; code?: string | null }
    return status === 403 && !!code && EXPECTED_AUTHORIZATION_CODES.has(code)
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
