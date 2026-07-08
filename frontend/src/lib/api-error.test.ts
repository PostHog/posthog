import { ApiError, isTransientNetworkError } from 'lib/api-error'

describe('api-error', () => {
    // Guards the reverse-proxy-check noise fix: a wrapped `fetch` failure (TypeError with no HTTP
    // status) must be recognised as transient so advisory checks skip capturing it, while a genuine
    // ApiError carrying a status must NOT be swallowed.
    it.each([
        ['raw TypeError from a failed fetch', new TypeError('Failed to fetch'), true],
        ['AbortError from an aborted request', Object.assign(new Error('aborted'), { name: 'AbortError' }), true],
        ['ApiError wrapping a fetch failure (no status)', new ApiError(String(new TypeError('Failed to fetch'))), true],
        ['ApiError wrapping an offline NetworkError', new ApiError('NetworkError when attempting to fetch'), true],
        ['ApiError with a real 500 status', new ApiError('A server error occurred', 500), false],
        ['ApiError with a 400 status', new ApiError('Bad request', 400), false],
        ['ApiError with no status but a non-network message', new ApiError('Something specific broke'), false],
        ['a plain Error', new Error('boom'), false],
        ['a null error', null, false],
    ])('classifies %s', (_desc, error, expected) => {
        expect(isTransientNetworkError(error)).toBe(expected)
    })
})
