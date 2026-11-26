import { ApiError } from 'lib/api'

/** What the server says about a date range it refuses as too long, or null for any other failure. */
export function rangeTooLongDetail(error: unknown): string | null {
    return error instanceof ApiError && error.status === 422 && error.code === 'range_too_long' && error.detail
        ? error.detail
        : null
}
