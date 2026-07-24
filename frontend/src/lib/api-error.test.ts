import { ApiError, isNetworkError } from './api-error'

describe('isNetworkError', () => {
    it.each([
        // transient fetch failures wrapped by handleFetch — no status
        ['ApiError with no status', new ApiError('TypeError: Failed to fetch', undefined), true],
        // raw browser fetch rejections, message varies by browser
        ['Chrome/Edge TypeError', new TypeError('Failed to fetch'), true],
        ['Firefox TypeError', new TypeError('NetworkError when attempting to fetch resource.'), true],
        ['Safari TypeError', new TypeError('Load failed'), true],
        // genuine API errors carry a status and must keep flowing through
        ['ApiError 404', new ApiError('Not found', 404), false],
        ['ApiError 500', new ApiError('Server error', 500), false],
        ['non-network Error', new Error('Something else broke'), false],
        ['non-error value', 'just a string', false],
    ])('classifies %s', (_name, error, expected) => {
        expect(isNetworkError(error)).toBe(expected)
    })
})
