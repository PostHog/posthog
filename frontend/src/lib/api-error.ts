import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

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

// Browser network messages produced when a `fetch` never reaches the server: offline, connection
// reset, DNS hiccup, ad-blocker, aborted navigation. Cross-browser wording varies, hence the set.
const NETWORK_ERROR_MESSAGE_RE =
    /Failed to fetch|NetworkError|Network request failed|Load failed|The (?:network|Internet) connection appears to be offline/i

/**
 * True for transient network failures that are outside our control (offline, connection reset,
 * ad-blocker, aborted navigation) rather than genuine defects. A failed `fetch` throws a raw
 * `TypeError`/`AbortError`; once wrapped by `api` (see `handleFetch`) it becomes an `ApiError`
 * with no HTTP status and one of the browser network messages above. Advisory background checks
 * can use this to skip capturing such errors to error tracking, where they are pure noise.
 */
export function isTransientNetworkError(error: unknown): boolean {
    if (error instanceof TypeError) {
        return true
    }
    const name = (error as { name?: string } | null | undefined)?.name
    if (name === 'AbortError' || name === 'TypeError') {
        return true
    }
    if (error instanceof ApiError) {
        // A wrapped fetch failure never got an HTTP response, so it carries no status.
        return error.status === undefined && NETWORK_ERROR_MESSAGE_RE.test(error.message)
    }
    return false
}
