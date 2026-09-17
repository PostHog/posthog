import { FetchResponse } from '~/common/utils/request'

import { MAX_RETRY_AFTER_MS, fetchErrorDetail, parseRetryAfterMs } from './cdp-fetch'

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

describe('parseRetryAfterMs', () => {
    const responseWith = (headers: Record<string, string>): FetchResponse => ({ status: 429, headers }) as FetchResponse

    beforeEach(() => {
        jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2025-01-01T00:00:00Z'))
    })

    it.each([
        ['a delay in seconds', { 'retry-after': '30' }, 30000],
        ['a delay capped at five minutes', { 'retry-after': '3600' }, MAX_RETRY_AFTER_MS],
        ['an HTTP date', { 'retry-after': 'Wed, 01 Jan 2025 00:00:10 GMT' }, 10000],
        ['a date in the past', { 'retry-after': 'Wed, 01 Jan 2025 00:00:00 GMT' }, undefined],
        ['an unparseable value', { 'retry-after': 'soon' }, undefined],
        ['no header', {}, undefined],
    ])('reads %s', (_name, headers, expected) => {
        expect(parseRetryAfterMs(responseWith(headers))).toBe(expected)
    })
})
