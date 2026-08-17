import { humanizeQueryError } from '~/queries/nodes/DataTable/humanizeQueryError'

describe('humanizeQueryError', () => {
    const SERVER_MESSAGE = "This query couldn't be completed. Wait a moment, then try again."
    const AUTH_MESSAGE = 'Your session may have expired. Refresh the page and try again.'

    it.each([
        ['ClickHouse error while executing query.', 500, SERVER_MESSAGE],
        ['A server error occurred.', 500, SERVER_MESSAGE],
        ['An internal server error occurred. Please try again later.', 503, SERVER_MESSAGE],
        ['Authentication credentials were not provided.', 401, AUTH_MESSAGE],
    ])('rewrites %p (status %p) to a message with a next step', (rawError, status, expected) => {
        expect(humanizeQueryError(rawError, status)).toBe(expected)
    })

    it.each([
        ['Unknown function foo', 400],
        ['Query timed out', undefined],
    ])('keeps %p (status %p) so an actionable error is not hidden', (rawError, status) => {
        expect(humanizeQueryError(rawError, status)).toBe(rawError)
    })
})
