import { isExpectedNetworkError } from '~/toolbar/toolbarApi'

describe('toolbarApi', () => {
    describe('isExpectedNetworkError', () => {
        it.each([
            ['Chrome offline/blocked', new TypeError('Failed to fetch')],
            ['Firefox', new TypeError('NetworkError when attempting to fetch resource.')],
            ['Safari', new TypeError('Load failed')],
            ['React Native', new TypeError('Network request failed')],
            ['region-suffixed', new TypeError('Failed to fetch (us)')],
        ])('treats a transient %s failure as expected', (_label, error) => {
            expect(isExpectedNetworkError(error)).toBe(true)
        })

        it('treats an aborted request (DOMException) as expected', () => {
            expect(isExpectedNetworkError(new DOMException('The user aborted a request.', 'AbortError'))).toBe(true)
        })

        it('treats an AbortError Error as expected', () => {
            const error = new Error('aborted')
            error.name = 'AbortError'
            expect(isExpectedNetworkError(error)).toBe(true)
        })

        it.each([
            ['a customer fetch wrapper throwing something unexpected', new TypeError('foo.bar is not a function')],
            ['a generic error', new Error('something broke')],
            ['a non-error value', { weird: true }],
            ['null', null],
        ])('reports %s as unexpected so it is still captured', (_label, error) => {
            expect(isExpectedNetworkError(error)).toBe(false)
        })
    })
})
