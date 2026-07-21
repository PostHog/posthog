import { ApiError, isNetworkError } from './api-error'

describe('isNetworkError', () => {
    it('treats a status-less ApiError (connectivity failure) as a network error', () => {
        // handleFetch wraps a `TypeError: Failed to fetch` in an ApiError with no HTTP status
        expect(isNetworkError(new ApiError('TypeError: Failed to fetch'))).toBe(true)
    })

    it('does not treat an ApiError with an HTTP status as a network error', () => {
        expect(isNetworkError(new ApiError('Not found', 404))).toBe(false)
        expect(isNetworkError(new ApiError('Server error', 500))).toBe(false)
    })

    it('does not treat a plain Error as a network error', () => {
        expect(isNetworkError(new Error('boom'))).toBe(false)
        expect(isNetworkError(new TypeError('Failed to fetch'))).toBe(false)
    })
})
