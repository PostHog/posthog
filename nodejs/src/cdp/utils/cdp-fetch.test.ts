import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { logger } from '~/common/utils/logger'
import { FetchResponse } from '~/common/utils/request'

import {
    MAX_RETRY_AFTER_MS,
    cdpTrackedFetch,
    fetchErrorDetail,
    getNextRetryTime,
    parseRetryAfterMs,
    recordRequestOrigins,
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

describe('recordRequestOrigins', () => {
    const send = (url: string) => cdpTrackedFetch({ url, fetchParams: { method: 'POST' }, templateId: 'template-test' })

    it('records each origin once, without the credentials, path or query of the URL', async () => {
        const origins = new Set<string>()

        await recordRequestOrigins(origins, async () => {
            await send('https://user:secret@example.com/hook?token=abc')
            await send('https://example.com/other')
            await send('http://localhost:8080/path')
        })

        expect([...origins].sort()).toEqual(['http://localhost:8080', 'https://example.com'])
    })

    it('records nothing for a request sent outside a recording', async () => {
        const origins = new Set<string>()
        await recordRequestOrigins(origins, () => Promise.resolve())

        await send('https://example.com/hook')

        expect([...origins]).toEqual([])
    })
})

describe('url scrubbing', () => {
    const url = 'https://discord.example.com:8443/api/webhooks/123/secret-token?wait=true'

    afterEach(() => {
        jest.restoreAllMocks()
        mockFetch.mockReset()
    })

    it('logs and returns the origin of the URL and never its path or query', async () => {
        const warn = jest.spyOn(logger, 'warn').mockImplementation(() => undefined)
        const socketError = Object.assign(new Error(`other side closed while sending to ${url}`), {
            code: 'UND_ERR_SOCKET',
        })
        mockFetch.mockRejectedValueOnce(socketError).mockRejectedValueOnce(socketError)

        const { fetchError } = await cdpTrackedFetch({
            url,
            fetchParams: { method: 'POST' },
            templateId: 'template-discord',
        })

        const retryLog = warn.mock.calls.find(([, message]) => String(message).includes('Connection-level error'))
        expect(retryLog?.[2]).toMatchObject({
            origin: 'https://discord.example.com:8443',
            error: { code: 'UND_ERR_SOCKET' },
        })
        const logged = JSON.stringify(warn.mock.calls) + fetchError?.message + fetchError?.stack
        expect(logged).not.toContain('/api/webhooks')
        expect(logged).not.toContain('secret-token')
        expect(logged).not.toContain('wait=true')
    })

    it('returns a DOMException timeout as the fetch error, with the URL scrubbed', async () => {
        mockFetch.mockRejectedValueOnce(new DOMException(`Timed out sending to ${url}`, 'TimeoutError'))

        const { fetchError } = await cdpTrackedFetch({
            url,
            fetchParams: { method: 'POST' },
            templateId: 'template-discord',
        })

        expect({ name: fetchError?.name, message: fetchError?.message }).toEqual({
            name: 'TimeoutError',
            message: 'Timed out sending to https://discord.example.com:8443',
        })
        expect(fetchError?.stack).not.toContain('secret-token')
    })
})

describe('Retry-After', () => {
    const now = DateTime.fromISO('2025-01-01T00:00:00.000Z', { zone: 'UTC' })

    const response = (status: number, headers: Record<string, string> = {}): FetchResponse =>
        ({ status, headers }) as unknown as FetchResponse

    beforeEach(() => {
        jest.spyOn(Date, 'now').mockReturnValue(now.toMillis())
        jest.spyOn(Math, 'random').mockReturnValue(0.5)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('parseRetryAfterMs', () => {
        it.each([
            ['delta-seconds', response(429, { 'retry-after': '60' }), 60_000],
            ['fractional delta-seconds', response(429, { 'retry-after': '1.5' }), 1_500],
            ['an HTTP-date', response(429, { 'retry-after': 'Wed, 01 Jan 2025 00:00:45 GMT' }), 45_000],
            ['a 503 with delta-seconds', response(503, { 'retry-after': '30' }), 30_000],
        ])('reads %s', (_name, res, expected) => {
            expect(parseRetryAfterMs(res)).toBe(expected)
        })

        it.each([
            ['delta-seconds', '86400'],
            ['an HTTP-date', 'Thu, 02 Jan 2025 00:00:00 GMT'],
        ])('caps a huge value given as %s', (_name, header) => {
            expect(parseRetryAfterMs(response(429, { 'retry-after': header }))).toBe(MAX_RETRY_AFTER_MS)
        })

        it.each([
            ['no response', null],
            ['no header', response(429)],
            ['an unparseable header', response(429, { 'retry-after': 'soon' })],
            ['zero seconds', response(429, { 'retry-after': '0' })],
            ['negative seconds', response(429, { 'retry-after': '-5' })],
            ['a date in the past', response(429, { 'retry-after': 'Tue, 31 Dec 2024 23:59:00 GMT' })],
            ['a status that is not rate limiting', response(500, { 'retry-after': '60' })],
        ])('returns undefined for %s', (_name, res) => {
            expect(parseRetryAfterMs(res)).toBeUndefined()
        })
    })

    describe('getNextRetryTime', () => {
        it.each([
            ['no Retry-After keeps the linear backoff', 1, undefined, '2025-01-01T00:00:01.500Z'],
            ['a Retry-After longer than the backoff wins', 1, 60_000, '2025-01-01T00:01:00.000Z'],
            ['a backoff longer than the Retry-After wins', 3, 1_000, '2025-01-01T00:00:03.500Z'],
            [
                'a Retry-After is bounded by its own cap, not the backoff cap',
                1,
                MAX_RETRY_AFTER_MS,
                '2025-01-01T00:05:00.000Z',
            ],
        ])('%s', (_name, tries, retryAfterMs, expected) => {
            expect(getNextRetryTime(1000, 30000, tries, retryAfterMs).toISO()).toBe(expected)
        })
    })
})
