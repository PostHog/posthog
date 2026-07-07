import { isNetworkError } from './isNetworkError'

describe('isNetworkError', () => {
    it.each([
        ['Chrome/Edge', new TypeError('Failed to fetch')],
        ['Firefox', new TypeError('NetworkError when attempting to fetch resource.')],
        ['Safari', new TypeError('Load failed')],
    ])('treats a %s fetch failure as a network error', (_browser, error) => {
        expect(isNetworkError(error)).toBe(true)
    })

    it.each([
        ['a genuine bug (different error type)', new SyntaxError('Failed to fetch')],
        ['an unrelated TypeError', new TypeError('Cannot read properties of undefined')],
        ['a plain Error', new Error('Failed to fetch')],
        ['a non-error value', 'Failed to fetch'],
        ['null', null],
    ])('does not treat %s as a network error', (_desc, error) => {
        expect(isNetworkError(error)).toBe(false)
    })
})
