/**
 * Turn a raw query failure into a short message a person can act on.
 *
 * The backend sends technical text for server faults: a 500 carries strings like
 * "ClickHouse error while executing query." or DRF's "A server error occurred.", and a
 * 401 carries "Authentication credentials were not provided.". None of these tell a
 * reader what to do, so the activity table shows a wall of red text with no next step.
 *
 * We only rewrite server faults (5xx) and auth failures (401). A 4xx from a HogQL query
 * usually carries a message the reader can act on (a bad column, a syntax error), so we
 * keep that text. When the status is unknown, we keep the raw message too, so this never
 * hides more than it did before.
 */

const SERVER_ERROR_MESSAGE = "This query couldn't be completed. Wait a moment, then try again."
const AUTH_ERROR_MESSAGE = 'Your session may have expired. Refresh the page and try again.'

export function humanizeQueryError(responseError: string, status?: number): string {
    if (status === 401) {
        return AUTH_ERROR_MESSAGE
    }
    if (status !== undefined && status >= 500) {
        return SERVER_ERROR_MESSAGE
    }
    return responseError
}
