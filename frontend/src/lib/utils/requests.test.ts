import { isDeterministicClientError } from 'lib/utils/requests'

describe('isDeterministicClientError', () => {
    // A dashboard tile's failed query is retried unless this returns true, so the status boundary
    // here is what stops a deterministic 400 from being hammered several times before it surfaces.
    it.each([
        [400, true],
        [401, true],
        [403, true],
        [404, true],
        [422, true],
        // transient 4xx that can succeed on retry
        [408, false],
        [429, false],
        // server / network errors are retryable
        [500, false],
        [503, false],
        [504, false],
        [undefined, false],
    ])('status %s -> %s', (status, expected) => {
        expect(isDeterministicClientError({ status })).toBe(expected)
    })
})
