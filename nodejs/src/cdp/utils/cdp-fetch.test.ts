import { InvalidRequestError, SecureRequestError } from '~/common/utils/request'

import { cdpTrackedFetch, fetchErrorDetail, isFetchResponseRetriable } from './cdp-fetch'

describe('cdp-fetch', () => {
    describe('fetchErrorDetail', () => {
        // Guards the unpacking of AggregateError causes: undici throws it with an empty message when
        // every connection attempt fails, so falling back to `error.message` alone would turn a
        // diagnosable per-address failure back into an opaque "AggregateError: ".
        it.each([
            [
                'a plain error keeps its message',
                new Error('connect ETIMEDOUT 10.0.0.1:443'),
                'connect ETIMEDOUT 10.0.0.1:443',
            ],
            [
                'an empty-message AggregateError surfaces its causes',
                new AggregateError([
                    new Error('connect ECONNREFUSED 1.2.3.4:443'),
                    new Error('connect ENETUNREACH ::1:443'),
                ]),
                'connect ECONNREFUSED 1.2.3.4:443; connect ENETUNREACH ::1:443',
            ],
            [
                'an AggregateError with a message appends its causes',
                new AggregateError([new Error('boom')], 'All attempts failed'),
                'All attempts failed (boom)',
            ],
            ['an AggregateError with no causes and no message stays empty', new AggregateError([]), ''],
        ])('%s', (_name, error, expected) => {
            expect(fetchErrorDetail(error)).toBe(expected)
        })
    })

    describe('cdpTrackedFetch header validation', () => {
        // undici refuses these values before it sends the request. The check must name the header
        // and the character, and the error must not be retried, because every retry fails the same way.
        it.each([
            ['a line break', { 'X-Test': 'first\nsecond' }, 'Header "X-Test"', 'U+000A', 'position 5'],
            [
                'a character outside Latin-1',
                [['X-Test', 'Sign up \u2014 now']],
                'Header "X-Test"',
                'U+2014',
                'position 8',
            ],
            ['a NUL character', { Authorization: 'Bearer \u0000' }, 'Header "Authorization"', 'U+0000', 'position 7'],
        ])('refuses a header value with %s', async (_name, headers, header, codePoint, position) => {
            const { fetchError, fetchResponse } = await cdpTrackedFetch({
                url: 'https://example.com/webhook',
                fetchParams: { method: 'POST', headers: headers as Record<string, string> },
                templateId: 'template-webhook',
            })

            expect(fetchResponse).toBeNull()
            expect(fetchError).toBeInstanceOf(InvalidRequestError)
            expect(fetchError!.message).toContain(header)
            expect(fetchError!.message).toContain(codePoint)
            expect(fetchError!.message).toContain(position)
            expect(isFetchResponseRetriable(fetchResponse, fetchError)).toBe(false)
        })
    })

    describe('isFetchResponseRetriable', () => {
        it.each([
            ['a general error', new Error('connect ECONNREFUSED 1.2.3.4:443'), true],
            ['a security error', new SecureRequestError('Hostname is not allowed'), false],
            [
                'an undici invalid argument error',
                Object.assign(new Error('invalid x-test header'), {
                    name: 'InvalidArgumentError',
                    code: 'UND_ERR_INVALID_ARG',
                }),
                false,
            ],
        ])('handles %s', (_name, error, expected) => {
            expect(isFetchResponseRetriable(null, error)).toBe(expected)
        })
    })
})
