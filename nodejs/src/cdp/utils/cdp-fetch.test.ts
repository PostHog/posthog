import { FetchResponse, InvalidRequestError, SecureRequestError } from '~/common/utils/request'

import { isFetchResponseRetriable, isTimeoutError } from './cdp-fetch'

describe('cdp-fetch', () => {
    describe('isTimeoutError', () => {
        it.each([
            ['TimeoutError', true],
            ['HeadersTimeoutError', true],
            ['BodyTimeoutError', true],
            ['SecureRequestError', false],
            ['SomeOtherError', false],
        ])('classifies a %s by name', (name, expected) => {
            expect(isTimeoutError({ name })).toBe(expected)
        })

        it('does not classify null or undefined as a timeout', () => {
            expect(isTimeoutError(null)).toBe(false)
            expect(isTimeoutError(undefined)).toBe(false)
        })
    })

    describe('isFetchResponseRetriable', () => {
        it('retries a timeout so a transiently slow endpoint gets another attempt', () => {
            const timeout = Object.assign(new Error('The operation was aborted due to timeout'), {
                name: 'TimeoutError',
            })
            expect(isFetchResponseRetriable(null, timeout)).toBe(true)
        })

        it.each([
            ['a blocked request', new SecureRequestError('blocked')],
            ['an invalid request', new InvalidRequestError('bad url')],
        ])('does not retry %s', (_label, error) => {
            expect(isFetchResponseRetriable(null, error)).toBe(false)
        })

        it('retries a retriable status code with no error', () => {
            expect(isFetchResponseRetriable({ status: 503 } as FetchResponse, null)).toBe(true)
            expect(isFetchResponseRetriable({ status: 400 } as FetchResponse, null)).toBe(false)
        })
    })
})
