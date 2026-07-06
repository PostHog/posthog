import { isNetworkError } from './requests'

describe('isNetworkError', () => {
    it.each([
        ['WebKit / Safari', new TypeError('Load failed')],
        ['Chromium', new TypeError('Failed to fetch')],
        ['Firefox', new TypeError('NetworkError when attempting to fetch resource.')],
        ['WebKit connection lost', new TypeError('The network connection was lost.')],
    ])('treats a %s network fetch failure as a network error', (_label, error) => {
        expect(isNetworkError(error)).toBe(true)
    })

    it.each([
        ['a genuine TypeError bug', new TypeError("Cannot read properties of undefined (reading 'foo')")],
        ['a non-TypeError with a matching message', new Error('Load failed')],
        ['an ApiError-like object', { status: 500, message: 'Load failed' }],
        ['an AbortError', Object.assign(new Error('aborted'), { name: 'AbortError' })],
    ])('does not treat %s as a network error', (_label, error) => {
        expect(isNetworkError(error)).toBe(false)
    })
})
