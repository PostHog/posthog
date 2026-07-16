import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

/** A 403 with DRF's `permission_denied` code — the user lacks access to the resource itself. */
export function isAccessDeniedError(error: { status?: number; code?: string | null }): boolean {
    return error.status === 403 && error.code === 'permission_denied'
}

// A `fetch()` that fails at the transport layer — the request never reached the server (client
// offline, DNS failure, aborted navigation, ad blocker / browser extension) — throws a `TypeError`
// whose message differs by engine. `handleFetch` rewraps these as an `ApiError` with no HTTP
// `status`, so we match on the message rather than the type.
const NETWORK_ERROR_MESSAGE_FRAGMENTS = [
    'Failed to fetch',
    'NetworkError when attempting to fetch resource',
    'Load failed',
]

/**
 * Whether an error is a transport-level fetch failure — a client-side network condition (offline,
 * DNS, aborted navigation, blocked by an extension) rather than an application defect. Requires the
 * absence of an HTTP status so a genuine error carrying one is never misclassified as network noise.
 */
export function isNetworkError(error: { status?: number; message?: string } | null | undefined): boolean {
    if (!error || error.status !== undefined) {
        return false
    }
    const message = error.message ?? ''
    return NETWORK_ERROR_MESSAGE_FRAGMENTS.some((fragment) => message.includes(fragment))
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
