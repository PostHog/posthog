import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

/** DRF error `code` for a 403 returned when the user must set up 2FA before continuing. */
export const TWO_FACTOR_SETUP_REQUIRED = 'two_factor_setup_required'
/** DRF error `code` for a 403 returned when the user's 2FA verification has expired. */
export const TWO_FACTOR_VERIFICATION_REQUIRED = 'two_factor_verification_required'
/** DRF error `code` for a 403 returned when a sensitive action needs fresh re-authentication. */
export const SENSITIVE_ACTION_REQUIRED_REAUTH = 'sensitive_action_required_reauth'

/**
 * Auth error codes that `apiStatusLogic` handles gracefully (opening the 2FA setup modal or
 * prompting re-authentication). Loader failures with these codes should not be toasted, logged,
 * or reported to error tracking — see `initKea`'s `loadersPlugin` `onFailure` handler.
 */
export const HANDLED_AUTH_ERROR_CODES: readonly string[] = [
    TWO_FACTOR_SETUP_REQUIRED,
    TWO_FACTOR_VERIFICATION_REQUIRED,
    SENSITIVE_ACTION_REQUIRED_REAUTH,
]

export function isHandledAuthErrorCode(code: string | null | undefined): boolean {
    return !!code && HANDLED_AUTH_ERROR_CODES.includes(code)
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
