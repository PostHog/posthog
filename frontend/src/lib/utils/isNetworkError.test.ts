import { isNetworkError } from './isNetworkError'

describe('isNetworkError', () => {
    it.each([
        ['Chromium fetch failure', { name: 'TypeError', message: 'Failed to fetch' }, true],
        ['Safari fetch failure', { name: 'TypeError', message: 'Load failed' }, true],
        [
            'Firefox fetch failure',
            { name: 'TypeError', message: 'NetworkError when attempting to fetch resource.' },
            true,
        ],
        // A parse error on the response body is a real bug, not a transient network blip.
        ['SyntaxError parsing the response', { name: 'SyntaxError', message: 'Unexpected token < in JSON' }, false],
        ['unrelated TypeError', { name: 'TypeError', message: 'undefined is not a function' }, false],
    ])('classifies %s', (_label, error, expected) => {
        expect(isNetworkError(error)).toBe(expected)
    })

    it.each([
        ['null', null],
        ['undefined', undefined],
        ['string', 'Failed to fetch'],
    ])('returns false for non-object %s', (_label, value) => {
        expect(isNetworkError(value)).toBe(false)
    })
})
