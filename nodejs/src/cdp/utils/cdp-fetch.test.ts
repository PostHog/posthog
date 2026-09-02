import { FetchResponse } from '~/common/utils/request'

import {
    MAX_FETCH_RETRY_AFTER_MS,
    RATE_LIMIT_BACKOFF_MAX_MS,
    RATE_LIMIT_MIN_RETRIES,
    fetchErrorDetail,
    getNextRetryTime,
    parseRetryAfterMs,
} from './cdp-fetch'

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
    const responseWithHeader = (value: string | undefined): FetchResponse =>
        ({ headers: value === undefined ? {} : { 'retry-after': value } }) as FetchResponse

    it('parses delta-seconds', () => {
        expect(parseRetryAfterMs(responseWithHeader('60'))).toBe(60_000)
    })

    it('parses an HTTP-date', () => {
        const ms = parseRetryAfterMs(responseWithHeader(new Date(Date.now() + 30_000).toUTCString()))
        expect(ms).toBeGreaterThan(0)
        expect(ms).toBeLessThanOrEqual(30_000)
    })

    it('caps a huge value so a hostile header cannot park an invocation for hours', () => {
        expect(parseRetryAfterMs(responseWithHeader('86400'))).toBe(MAX_FETCH_RETRY_AFTER_MS)
    })

    it.each([
        ['missing', undefined],
        ['unparseable', 'soon-ish'],
        ['zero', '0'],
        ['negative', '-5'],
        ['a date in the past', new Date(Date.now() - 30_000).toUTCString()],
    ])('returns undefined when the header is %s', (_name, value) => {
        expect(parseRetryAfterMs(responseWithHeader(value))).toBeUndefined()
    })
})

describe('getNextRetryTime', () => {
    const delayMs = (t: { toMillis: () => number }): number => t.toMillis() - Date.now()

    it('honors Retry-After with only jitter added', () => {
        const ms = delayMs(getNextRetryTime(1000, 30000, 1, { retryAfterMs: 60_000 }))
        expect(ms).toBeGreaterThanOrEqual(60_000)
        expect(ms).toBeLessThan(61_000)
    })

    it('keeps linear backoff for non-429 retriable failures', () => {
        for (let tries = 1; tries <= 3; tries++) {
            const ms = delayMs(getNextRetryTime(1000, 30000, tries))
            expect(ms).toBeGreaterThanOrEqual(1000 * tries)
            expect(ms).toBeLessThan(1000 * (tries + 1))
        }
    })

    it('backs off exponentially on 429 so retries can span a per-minute window', () => {
        const first = delayMs(getNextRetryTime(1000, 30000, 1, { isRateLimited: true }))
        const third = delayMs(getNextRetryTime(1000, 30000, 3, { isRateLimited: true }))
        expect(first).toBeGreaterThanOrEqual(1000)
        expect(first).toBeLessThan(2000)
        // linear backoff would cap this at ~3s, inside the window that already rejected us
        expect(third).toBeGreaterThanOrEqual(4000)
        expect(third).toBeLessThan(5000)
    })

    it('grows past a per-minute window within RATE_LIMIT_MIN_RETRIES attempts', () => {
        // the default 3-retry linear schedule dies in ~6s; 429 exponential reaches ~63s
        let total = 0
        for (let tries = 1; tries <= RATE_LIMIT_MIN_RETRIES; tries++) {
            total += 1000 * 2 ** (tries - 1)
        }
        expect(total).toBeGreaterThanOrEqual(60_000)
    })

    it('lets 429 retries reach past the generic cap, up to the rate-limit ceiling', () => {
        const ms = delayMs(getNextRetryTime(1000, 30000, 20, { isRateLimited: true }))
        expect(ms).toBeGreaterThan(30000)
        expect(ms).toBeLessThanOrEqual(RATE_LIMIT_BACKOFF_MAX_MS + 1000)
    })
})
