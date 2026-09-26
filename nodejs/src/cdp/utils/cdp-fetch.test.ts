import { FetchResponse } from '~/common/utils/request'

import { MAX_RETRY_AFTER_MS, fetchErrorDetail, getNextRetryTime, parseRetryAfterMs } from './cdp-fetch'

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

describe('getNextRetryTime', () => {
    const NOW = Date.parse('2025-01-01T00:00:00Z')
    const BACKOFF_BASE_MS = 1000
    const BACKOFF_MAX_MS = 30000

    const waitMs = (tries: number, retryAfterMs?: number): number =>
        getNextRetryTime(BACKOFF_BASE_MS, BACKOFF_MAX_MS, tries, retryAfterMs).toMillis() - NOW

    beforeEach(() => {
        jest.spyOn(Date, 'now').mockReturnValue(NOW)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    // The jitter has to scale with the interval it spreads. A fixed one-second spread on a
    // minutes-long provider interval wakes a whole rate-limited burst inside the same second, which
    // re-trips the limit the wait exists to clear.
    it.each([
        ['backs off without a provider interval', 1, undefined, 1500],
        ['clamps the backoff at the maximum', 100, undefined, BACKOFF_MAX_MS],
        ['keeps the backoff when the provider asks for less', 5, 200, 5500],
        ['spreads a short interval across itself', 1, 5000, 7500],
        ['spreads a long interval across the maximum backoff', 1, 60000, 75000],
        ['spreads a capped interval across the maximum backoff', 1, MAX_RETRY_AFTER_MS, 315000],
    ])('%s', (_name, tries, retryAfterMs, expected) => {
        jest.spyOn(Math, 'random').mockReturnValue(0.5)
        expect(waitMs(tries, retryAfterMs)).toBe(expected)
    })

    it('never waits less than the provider asked for, nor more than the bounded spread', () => {
        const waits = Array.from({ length: 200 }, () => waitMs(1, 60000))

        expect(Math.min(...waits)).toBeGreaterThanOrEqual(60000)
        expect(Math.max(...waits)).toBeLessThanOrEqual(60000 + BACKOFF_MAX_MS)
        expect(Math.max(...waits) - Math.min(...waits)).toBeGreaterThan(BACKOFF_BASE_MS)
    })
})
