import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

/** The pathname of a request URL, or null when the URL is missing or unparseable. */
function pathnameOrNull(url: string | undefined): string | null {
    if (!url) {
        return null
    }
    try {
        return new URL(url, location.origin).pathname
    } catch {
        return null
    }
}

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

    /**
     * The exact request path (with project IDs, UUIDs, etc.). Kept off the message — which error
     * tracking fingerprints on — so identical failures on different resources group into one issue,
     * while triage can still see which resource failed.
     */
    requestPath: string | null = null

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

        const error = new ApiError(responseMessage || fallbackMessage, response.status, response.headers, data)
        error.requestPath = pathnameOrNull(response.url)
        return error
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
