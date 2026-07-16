import { ApiError, isNetworkError } from './api-error'

describe('isNetworkError', () => {
    // The signature that must stay network noise (no HTTP status + an engine-specific transport
    // message) vs. real errors that must keep flowing to error tracking (anything with a status, or
    // a code bug whose message doesn't look like a fetch failure).
    it.each([
        ['Chrome transport failure', new ApiError('TypeError: Failed to fetch', undefined), true],
        ['Firefox transport failure', new ApiError('NetworkError when attempting to fetch resource.', undefined), true],
        ['Safari transport failure', new ApiError('TypeError: Load failed', undefined), true],
        ['raw TypeError before wrapping', new TypeError('Failed to fetch'), true],
        // A real HTTP error must never be misclassified as network noise, even if the body echoes
        // "Failed to fetch" — a status is present, so it still gets captured.
        ['500 with a network-ish message', new ApiError('Failed to fetch', 500), false],
        ['404', new ApiError('Not found', 404), false],
        ['code bug (undefined access)', new TypeError("Cannot read properties of undefined (reading 'x')"), false],
        ['null', null, false],
        ['undefined', undefined, false],
    ])('%s → %s', (_label, error, expected) => {
        expect(isNetworkError(error)).toBe(expected)
    })
})
