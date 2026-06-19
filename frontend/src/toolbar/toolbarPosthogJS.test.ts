import { isClientNetworkError } from './toolbarPosthogJS'

describe('isClientNetworkError', () => {
    it.each([
        ['Chrome fetch failure', new TypeError('Failed to fetch'), true],
        ['Firefox fetch failure', new TypeError('NetworkError when attempting to fetch resource'), true],
        ['Safari fetch failure', new TypeError('Load failed'), true],
        ['aborted/timed-out fetch', new DOMException('The operation timed out', 'AbortError'), true],
        ['generic Error', new Error('boom'), false],
        ['HTTP error thrown on !response.ok', new Error('HTTP 500'), false],
        ['JSON parse failure', new SyntaxError('Unexpected token < in JSON'), false],
        ['non-abort DOMException', new DOMException('nope', 'NotFoundError'), false],
        ['string', 'Failed to fetch', false],
        ['null', null, false],
    ])('treats %s as client network error = %s', (_label, error, expected) => {
        expect(isClientNetworkError(error)).toBe(expected)
    })
})
