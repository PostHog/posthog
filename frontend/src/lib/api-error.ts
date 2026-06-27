import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

/**
 * The exact `detail` the backend returns (with a 404) when an environment-scoped request targets a
 * team the user can no longer reach — a deleted team, revoked access, or a `currentTeamId` left stale
 * after an org/team switch. See `posthog/api/routing.py`.
 */
export const PROJECT_NOT_FOUND_DETAIL = 'Project not found.'

/**
 * True when `error` is the backend's "current environment is gone" 404. Loaders that fire on app-shell
 * mount (e.g. dashboards, conversation history) use this to degrade to an empty result instead of letting
 * the stale-team 404 reject into React render.
 */
export function isProjectNotFoundError(error: unknown): boolean {
    return error instanceof ApiError && error.isProjectNotFound
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

    /** Whether this is the backend's "current environment is gone" 404 — see `isProjectNotFoundError`. */
    get isProjectNotFound(): boolean {
        return this.status === 404 && this.detail === PROJECT_NOT_FOUND_DETAIL
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
