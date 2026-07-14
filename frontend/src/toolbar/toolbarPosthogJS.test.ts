import { isBenignNetworkError } from '~/toolbar/toolbarPosthogJS'

describe('isBenignNetworkError', () => {
    it.each([
        // Benign: fetch surfaces network/CORS/offline/ad-blocker failures as a TypeError.
        ['TypeError "Failed to fetch"', new TypeError('Failed to fetch'), true],
        ['TypeError "NetworkError"', new TypeError('NetworkError when attempting to fetch resource'), true],
        // Benign: AbortSignal.timeout() rejects with a TimeoutError; manual abort with AbortError.
        ['DOMException TimeoutError', new DOMException('timed out', 'TimeoutError'), true],
        ['DOMException AbortError', new DOMException('aborted', 'AbortError'), true],
        // Not benign: genuine failures that must still reach error tracking.
        ['HTTP status Error', new Error('HTTP 500'), false],
        ['malformed-JSON SyntaxError', new SyntaxError('Unexpected token < in JSON'), false],
        ['generic Error', new Error('something unexpected'), false],
        ['other DOMException', new DOMException('nope', 'InvalidStateError'), false],
        ['non-error string', 'boom', false],
        ['null', null, false],
    ])('classifies %s as benign=%s', (_label, error, expected) => {
        expect(isBenignNetworkError(error)).toBe(expected)
    })
})
