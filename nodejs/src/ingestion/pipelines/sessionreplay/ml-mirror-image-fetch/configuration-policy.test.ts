import { StreamedResponse, fetchStreamed } from '~/common/utils/request'

import {
    ConfigurationFetchResult,
    ConfigurationPolicyService,
    HttpConfigurationFetcher,
    explicitFreshnessLifetimeMs,
    parseRobotsPolicy,
    responseOptOutReason,
} from './configuration-policy'
import { ConfigurationCacheItem, ConfigurationFile, configurationCacheKey } from './crawl-history'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    fetchStreamed: jest.fn(),
}))

const fetchStreamedMock = fetchStreamed as jest.MockedFunction<typeof fetchStreamed>

const NOW_MS = Date.parse('2026-08-22T12:00:00Z')
const ORIGIN = 'https://example.com'

function cached(
    file: ConfigurationFile,
    status: ConfigurationCacheItem['status'],
    body?: string
): ConfigurationCacheItem {
    return {
        kind: file,
        key: configurationCacheKey(ORIGIN, file),
        origin: ORIGIN,
        status,
        body,
        fetchedAtMs: NOW_MS,
        refreshAtMs: NOW_MS + 23 * 60 * 60 * 1000,
        freshUntilMs: NOW_MS + 24 * 60 * 60 * 1000,
        retryAtMs: NOW_MS,
        storageExpiresAtMs: NOW_MS + 30 * 24 * 60 * 60 * 1000,
    }
}

function service(results: Partial<Record<ConfigurationFile, ConfigurationFetchResult>> = {}): {
    policy: ConfigurationPolicyService
    fetch: jest.Mock
} {
    const fetch = jest.fn((_: string, file: ConfigurationFile) =>
        Promise.resolve(results[file] ?? ({ outcome: 'absent' } as const))
    )
    return {
        policy: new ConfigurationPolicyService({ fetch } as unknown as HttpConfigurationFetcher),
        fetch,
    }
}

function response(
    status: number,
    headerLines: Array<{ name: string; value: string }> = [],
    body: { bytes: Buffer; overLimit: boolean } = { bytes: Buffer.alloc(0), overLimit: false }
): StreamedResponse {
    return {
        status,
        headers: Object.fromEntries(headerLines.map(({ name, value }) => [name, value])),
        headerLines,
        read: jest.fn().mockResolvedValue(body),
        discard: jest.fn(),
    }
}

function httpFetcher(headersForGet = jest.fn().mockReturnValue({})): HttpConfigurationFetcher {
    return new HttpConfigurationFetcher(
        { headersForGet },
        {
            run: async (_url, _deadlineMs, request) => ({ ran: true as const, value: await request() }),
        },
        5_000
    )
}

describe('robots policy', () => {
    it('uses the RFC 9309 group and path matcher', async () => {
        const body = [
            'User-agent: *',
            'Disallow: /wildcard',
            'User-agent: PostHogImageFetcherBot',
            'Disallow: /private',
            'Allow: /private/public.png',
        ].join('\n')

        await expect(parseRobotsPolicy(body, `${ORIGIN}/private/image.png`)).resolves.toMatchObject({
            allowed: false,
            reason: 'robots_disallow',
        })
        await expect(parseRobotsPolicy(body, `${ORIGIN}/private/public.png`)).resolves.toMatchObject({
            allowed: true,
            crawlDelayMs: 0,
        })
        await expect(parseRobotsPolicy(body, `${ORIGIN}/wildcard/image.png`)).resolves.toMatchObject({
            allowed: true,
            crawlDelayMs: 0,
        })
    })

    it('uses the greatest valid crawl delay in every selected field line', async () => {
        const body = [
            'User-agent: PostHogImageFetcherBot',
            'Crawl-delay: 0.25',
            'Crawl-delay: invalid',
            'Crawl-delay: 0x10',
            'Crawl-delay: 1e3',
            'Crawl-delay: 2.5',
            // 16.1 * 1000 is 16100.000000000002, which is not a safe integer.
            'Crawl-delay: 16.1',
            'Allow: /',
        ].join('\n')

        const result = await parseRobotsPolicy(body, `${ORIGIN}/image.png`)
        expect(result).toMatchObject({
            allowed: true,
            crawlDelayMs: 16_100,
        })
    })

    it.each([
        ['a token refusal', 'train-ai=n', false],
        ['a later allowance', 'train-ai=n, train-ai=y', true],
        ['a quoted value', 'train-ai="n"', true],
        ['a boolean value', 'train-ai=?0', true],
        ['an invalid dictionary', 'train-ai=n, INVALID=y', true],
    ])('applies Content-Usage with %s', async (_name, value, allowed) => {
        const body = `User-agent: *\nContent-Usage: ${value}\nAllow: /`

        await expect(parseRobotsPolicy(body, `${ORIGIN}/image.png`)).resolves.toMatchObject({ allowed })
    })

    it('applies a path-scoped Content-Signal only to a matching URL', async () => {
        const body = 'User-agent: *\nContent-Signal: /private/ ai-train=no, search=yes\nAllow: /'

        await expect(parseRobotsPolicy(body, `${ORIGIN}/private/image.png`)).resolves.toMatchObject({
            allowed: false,
            reason: 'content_signal',
        })
        await expect(parseRobotsPolicy(body, `${ORIGIN}/public/image.png`)).resolves.toMatchObject({ allowed: true })
    })
})

describe('response opt-out policy', () => {
    it('uses the last duplicate Content-Usage dictionary member', () => {
        expect(
            responseOptOutReason(
                [
                    { name: 'content-usage', value: 'train-ai=n' },
                    { name: 'content-usage', value: 'train-ai=y' },
                ],
                false
            )
        ).toBeUndefined()
        expect(
            responseOptOutReason(
                [
                    { name: 'content-usage', value: 'train-ai=y' },
                    { name: 'content-usage', value: 'train-ai=n' },
                ],
                false
            )
        ).toBe('content_usage')
    })

    it('lets the response TDM value override the tdmrep file', () => {
        expect(responseOptOutReason([{ name: 'tdm-reservation', value: '0' }], true)).toBeUndefined()
        expect(responseOptOutReason([{ name: 'tdm-reservation', value: '1' }], false)).toBe('tdm_reservation')
    })

    it.each([
        ['a scope for this bot', 'PostHogImageFetcherBot: noindex, noimageai', 'x_robots_tag'],
        ['a scope for another bot', 'OtherBot: noai', undefined],
        [
            'no scope beside a colon-bearing directive',
            'noai, unavailable_after: 25 Jun 2026 15:00:00 PST',
            'x_robots_tag',
        ],
        [
            'a scope for another bot beside a colon-bearing directive',
            'OtherBot: noai, unavailable_after: 25 Jun 2026 15:00:00 PST',
            undefined,
        ],
        [
            'no scope after a leading valued directive',
            'unavailable_after: 25 Jun 2026 15:00:00 PST, noai',
            'x_robots_tag',
        ],
        ['no scope after a leading max-image-preview', 'max-image-preview: large, noai', 'x_robots_tag'],
        [
            'a scope for another bot before a valued directive',
            'OtherBot: unavailable_after: 25 Jun 2026 15:00:00 PST, noai',
            undefined,
        ],
    ])('applies an X-Robots-Tag value with %s', (_name, value, expected) => {
        expect(responseOptOutReason([{ name: 'x-robots-tag', value }], false)).toBe(expected)
    })
})

describe('ConfigurationPolicyService', () => {
    it('checks both files before it allows an image request', async () => {
        const { policy, fetch } = service()

        await expect(policy.check(`${ORIGIN}/image.png`, new Map(), NOW_MS)).resolves.toMatchObject({ allowed: true })
        expect(fetch.mock.calls).toEqual([
            [ORIGIN, 'robots'],
            [ORIGIN, 'tdmrep'],
        ])
    })

    it('uses a cached configuration without a new request', async () => {
        const { policy, fetch } = service()
        const cache = new Map([
            [configurationCacheKey(ORIGIN, 'robots'), cached('robots', 'absent')],
            [configurationCacheKey(ORIGIN, 'tdmrep'), cached('tdmrep', 'absent')],
        ])

        await expect(policy.check(`${ORIGIN}/image.png`, cache, NOW_MS)).resolves.toMatchObject({ allowed: true })
        expect(fetch).not.toHaveBeenCalled()
    })

    it('parses each cached policy revision once in a fetch pass', async () => {
        const { ParsedRobots } = await import('@trybyte/robotstxt-parser')
        const parseRobots = jest.spyOn(ParsedRobots, 'parse')
        const parseJson = jest.spyOn(JSON, 'parse')
        const { policy } = service()
        const robotsBody = 'User-agent: *\nAllow: /'
        const tdmrepBody = JSON.stringify([{ location: '/', 'tdm-reservation': 0 }])
        const cache = new Map([
            [configurationCacheKey(ORIGIN, 'robots'), cached('robots', 'available', robotsBody)],
            [configurationCacheKey(ORIGIN, 'tdmrep'), cached('tdmrep', 'available', tdmrepBody)],
        ])

        try {
            const pass = policy.createPass()
            await pass.check(`${ORIGIN}/first.png`, cache, NOW_MS)
            await pass.check(`${ORIGIN}/second.png`, cache, NOW_MS)

            expect(parseRobots.mock.calls.filter(([body]) => body === robotsBody)).toHaveLength(1)
            expect(parseJson.mock.calls.filter(([body]) => body === tdmrepBody)).toHaveLength(1)

            const revisedCache = new Map(
                [...cache].map(([key, item]) => [key, { ...item, fetchedAtMs: item.fetchedAtMs + 1 }] as const)
            )
            await pass.check(`${ORIGIN}/third.png`, revisedCache, NOW_MS)

            expect(parseRobots.mock.calls.filter(([body]) => body === robotsBody)).toHaveLength(2)
            expect(parseJson.mock.calls.filter(([body]) => body === tdmrepBody)).toHaveLength(2)

            await policy.createPass().check(`${ORIGIN}/fourth.png`, cache, NOW_MS)

            expect(parseRobots.mock.calls.filter(([body]) => body === robotsBody)).toHaveLength(3)
            expect(parseJson.mock.calls.filter(([body]) => body === tdmrepBody)).toHaveLength(3)
        } finally {
            parseRobots.mockRestore()
            parseJson.mockRestore()
        }
    })

    it('uses the first matching TDMRep rule and honors the end anchor', async () => {
        const { policy } = service()
        const cache = new Map([
            [configurationCacheKey(ORIGIN, 'robots'), cached('robots', 'absent')],
            [
                configurationCacheKey(ORIGIN, 'tdmrep'),
                cached(
                    'tdmrep',
                    'available',
                    JSON.stringify([
                        { location: '/private/exact$', 'tdm-reservation': 0 },
                        { location: '/private/*', 'tdm-reservation': 1 },
                    ])
                ),
            ],
        ])

        await expect(policy.check(`${ORIGIN}/private/exact`, cache, NOW_MS)).resolves.toMatchObject({ allowed: true })
        await expect(policy.check(`${ORIGIN}/private/exact-more`, cache, NOW_MS)).resolves.toMatchObject({
            allowed: true,
            tdmrepReservation: true,
        })
    })

    it('keeps a previous usable file when its refresh is unreachable', async () => {
        const { policy } = service({ robots: { outcome: 'unreachable' } })
        const previous = { ...cached('robots', 'absent'), refreshAtMs: NOW_MS - 1 }
        const cache = new Map([
            [configurationCacheKey(ORIGIN, 'robots'), previous],
            [configurationCacheKey(ORIGIN, 'tdmrep'), cached('tdmrep', 'absent')],
        ])

        await expect(policy.check(`${ORIGIN}/image.png`, cache, NOW_MS)).resolves.toMatchObject({
            allowed: true,
            updates: [expect.objectContaining({ kind: 'robots', status: 'absent', retryAtMs: NOW_MS + 3_600_000 })],
        })
    })

    it('returns a transient refusal when no configuration file is reachable', async () => {
        const { policy } = service({ robots: { outcome: 'unreachable' } })

        await expect(policy.check(`${ORIGIN}/image.png`, new Map(), NOW_MS)).resolves.toMatchObject({
            allowed: false,
            transient: true,
            reason: 'configuration_unreachable',
        })
    })

    it('preserves a registrable-domain state deferral', async () => {
        const { policy } = service({
            robots: { outcome: 'deferred', reason: 'registrable_domain_map_full' },
        })

        await expect(policy.check(`${ORIGIN}/image.png`, new Map(), NOW_MS)).resolves.toMatchObject({
            allowed: false,
            transient: true,
            reason: 'registrable_domain_map_full',
        })
    })

    it('keeps a terminal refusal when the other configuration file is unreachable', async () => {
        const { policy } = service({
            robots: {
                outcome: 'available',
                body: 'User-agent: *\nDisallow: /private',
                cache: { requestTimeMs: NOW_MS, responseTimeMs: NOW_MS },
            },
            tdmrep: { outcome: 'unreachable' },
        })

        await expect(policy.check(`${ORIGIN}/private/image.png`, new Map(), NOW_MS)).resolves.toMatchObject({
            allowed: false,
            transient: false,
            reason: 'robots_disallow',
        })
    })
})

describe('HttpConfigurationFetcher', () => {
    beforeEach(() => {
        fetchStreamedMock.mockReset()
    })

    it.each([
        [404, 'absent'],
        [410, 'absent'],
        [401, 'refused'],
        [403, 'refused'],
        [429, 'unreachable'],
        [500, 'unreachable'],
        [204, 'unreachable'],
    ])('maps HTTP %s to %s', async (status, outcome) => {
        fetchStreamedMock.mockResolvedValue(response(status))

        await expect(httpFetcher().fetch(ORIGIN, 'robots')).resolves.toMatchObject({ outcome })
    })

    it('uses the retained prefix when robots.txt exceeds its byte limit', async () => {
        fetchStreamedMock.mockResolvedValue(
            response(200, [], {
                bytes: Buffer.concat([
                    Buffer.from('User-agent: *\nDisallow: /private'),
                    Buffer.from([0xf0, 0x9f, 0x98]),
                ]),
                overLimit: true,
            })
        )

        await expect(httpFetcher().fetch(ORIGIN, 'robots')).resolves.toMatchObject({
            outcome: 'available',
            body: 'User-agent: *\nDisallow: /private',
        })
    })

    it('treats invalid UTF-8 configuration text as unreachable', async () => {
        fetchStreamedMock.mockResolvedValue(
            response(200, [], { bytes: Buffer.from([0x75, 0x73, 0x65, 0x72, 0xff]), overLimit: false })
        )

        await expect(httpFetcher().fetch(ORIGIN, 'robots')).resolves.toMatchObject({ outcome: 'unreachable' })
    })

    it('treats an oversized or invalid TDMRep document as unreachable', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(response(200, [], { bytes: Buffer.from('[]'), overLimit: true }))
            .mockResolvedValueOnce(response(200, [], { bytes: Buffer.from('{invalid'), overLimit: false }))

        await expect(httpFetcher().fetch(ORIGIN, 'tdmrep')).resolves.toMatchObject({ outcome: 'unreachable' })
        await expect(httpFetcher().fetch(ORIGIN, 'tdmrep')).resolves.toMatchObject({ outcome: 'unreachable' })
    })

    it('treats repeated Location field lines as unreachable', async () => {
        fetchStreamedMock.mockResolvedValue(
            response(302, [
                { name: 'location', value: '/first' },
                { name: 'location', value: '/second' },
            ])
        )

        await expect(httpFetcher().fetch(ORIGIN, 'robots')).resolves.toMatchObject({ outcome: 'unreachable' })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
    })

    it('follows and signs each configuration redirect target', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(response(302, [{ name: 'location', value: 'https://cdn.example.com/robots' }]))
            .mockResolvedValueOnce(
                response(200, [], { bytes: Buffer.from('User-agent: *\nAllow: /'), overLimit: false })
            )
        const headersForGet = jest
            .fn()
            .mockReturnValueOnce({ signature: 'first' })
            .mockReturnValueOnce({ signature: 'second' })

        await expect(httpFetcher(headersForGet).fetch(ORIGIN, 'robots')).resolves.toMatchObject({
            outcome: 'available',
        })
        expect(headersForGet.mock.calls).toEqual([
            ['https://example.com/robots.txt'],
            ['https://cdn.example.com/robots'],
        ])
    })

    it('does not follow a configuration redirect to another registrable domain', async () => {
        fetchStreamedMock.mockResolvedValueOnce(
            response(302, [{ name: 'location', value: 'https://cdn.example.net/robots' }])
        )
        const headersForGet = jest.fn().mockReturnValue({ signature: 'value' })

        await expect(httpFetcher(headersForGet).fetch(ORIGIN, 'robots')).resolves.toMatchObject({
            outcome: 'unreachable',
        })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
        expect(headersForGet).toHaveBeenCalledTimes(1)
    })
})

describe('explicitFreshnessLifetimeMs', () => {
    it('uses s-maxage and subtracts the corrected current age', () => {
        expect(
            explicitFreshnessLifetimeMs(
                {
                    requestTimeMs: NOW_MS - 2_000,
                    responseTimeMs: NOW_MS,
                    date: new Date(NOW_MS - 1_000).toUTCString(),
                    age: '10',
                    cacheControl: 'max-age=100, s-maxage=200',
                },
                NOW_MS
            )
        ).toBe(188_000)
    })

    it.each(['no-cache', 'no-store', 'private', 'must-revalidate'])('does not extend freshness for %s', (directive) => {
        expect(
            explicitFreshnessLifetimeMs(
                {
                    requestTimeMs: NOW_MS,
                    responseTimeMs: NOW_MS,
                    cacheControl: `${directive}, max-age=999999`,
                },
                NOW_MS
            )
        ).toBe(0)
    })

    it.each([
        ['duplicate max-age', 'max-age=60, max-age=120'],
        ['decimal max-age', 'max-age=1.5'],
        ['exponent max-age', 'max-age=1e3'],
        ['unsafe max-age', 'max-age=9007199254740992'],
        ['invalid s-maxage before a valid max-age', 's-maxage=invalid, max-age=3600'],
    ])('does not extend freshness for %s', (_name, cacheControl) => {
        expect(
            explicitFreshnessLifetimeMs(
                {
                    requestTimeMs: NOW_MS,
                    responseTimeMs: NOW_MS,
                    cacheControl,
                },
                NOW_MS
            )
        ).toBe(0)
    })

    it('uses every combined Cache-Control field line', () => {
        expect(
            explicitFreshnessLifetimeMs(
                {
                    requestTimeMs: NOW_MS,
                    responseTimeMs: NOW_MS,
                    cacheControl: 'public, max-age=86400, no-store',
                },
                NOW_MS
            )
        ).toBe(0)
    })

    it('ignores a decimal Age value', () => {
        expect(
            explicitFreshnessLifetimeMs(
                {
                    requestTimeMs: NOW_MS,
                    responseTimeMs: NOW_MS,
                    age: '1.5',
                    cacheControl: 'max-age=10',
                },
                NOW_MS
            )
        ).toBe(10_000)
    })

    it('subtracts time spent resident after the response arrived', () => {
        expect(
            explicitFreshnessLifetimeMs(
                {
                    requestTimeMs: NOW_MS,
                    responseTimeMs: NOW_MS,
                    cacheControl: 'max-age=10',
                },
                NOW_MS + 4_000
            )
        ).toBe(6_000)
    })
})
