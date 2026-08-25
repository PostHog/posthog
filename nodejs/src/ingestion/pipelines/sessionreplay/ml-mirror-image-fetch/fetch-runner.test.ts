import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { ConfigurationPolicyService, OriginPolicyDecision } from './configuration-policy'
import { ConfigurationCacheItem, CrawlHistoryItem, HttpCacheMetadata } from './crawl-history'
import { DELAY_TOO_LONG, FetchRunner, FetchRunnerOptions, HOPS_EXHAUSTED } from './fetch-runner'
import { FrontierPublisher, RepublishResult } from './frontier-publisher'
import { HostBudget } from './host-budget'
import { ImageFetchOptions, ImageFetchResult, ImageFetcher } from './image-fetcher'
import { OriginRequestScheduler } from './origin-request-scheduler'

const NOW_MS = 1_700_000_000_000
const OPTIONS: FetchRunnerOptions = {
    maxConcurrentPerRegistrableDomain: 2,
    maxInFlightRequests: 50,
    batchBudgetMs: 20_000,
    maxBytes: 20 * 1024 * 1024,
    requestTimeoutMs: 10_000,
    maxRedirects: 3,
    seenTtlSeconds: 30 * 24 * 60 * 60,
}

function candidate(overrides: Partial<FetchCandidate> = {}): FetchCandidate {
    return {
        originalRef: `imageurl:${'a'.repeat(22)}`,
        currentUrl: 'https://cdn.example.com/a.png',
        host: 'cdn.example.com',
        origin: 'https://cdn.example.com',
        registrableDomain: 'example.com',
        remainingHops: MAX_HOPS,
        notBeforeMs: 0,
        firstSeenAtMs: NOW_MS - 1_000,
        fetchCount: 0,
        republishCount: 0,
        lastRepublishReason: null,
        ...overrides,
    }
}

interface Harness {
    runner: FetchRunner
    fetch: jest.Mock<Promise<ImageFetchResult>, [string, ImageFetchOptions]>
    check: jest.Mock<Promise<OriginPolicyDecision>, [string, Map<string, ConfigurationCacheItem>, number]>
    createPass: jest.Mock
    republish: jest.Mock<Promise<RepublishResult>, any[]>
    publishImage: jest.Mock<Promise<void>, any[]>
}

function build(
    result: Partial<ImageFetchResult> = {},
    policy: Partial<OriginPolicyDecision> = {},
    republishResult: RepublishResult = 'queued',
    options: FetchRunnerOptions = OPTIONS
): Harness {
    const fetch = jest.fn((url: string, _options: ImageFetchOptions) =>
        Promise.resolve({ outcome: 'ok', redirects: 0, currentUrl: url, ...result } as ImageFetchResult)
    )
    const check = jest.fn((_url: string, _cached: Map<string, ConfigurationCacheItem>, _nowMs: number) =>
        Promise.resolve({
            allowed: true,
            transient: false,
            crawlDelayMs: 1_000,
            tdmrepReservation: false,
            updates: [],
            ...policy,
        } as OriginPolicyDecision)
    )
    const createPass = jest.fn(() => ({ check }))
    const republish = jest.fn(() => Promise.resolve(republishResult))
    const createRepublishBatch = jest.fn(() => ({ republish, flush: () => Promise.resolve({ failedUrls: 0 }) }))
    const publishImage = jest.fn(() => Promise.resolve())
    const scheduler = {
        runImage: async (_url: URL, _deadlineMs: number, request: () => Promise<ImageFetchResult>) => ({
            ran: true as const,
            value: await request(),
        }),
        authorizeImageRedirect: () => Promise.resolve(true),
    } as unknown as OriginRequestScheduler
    const budget = new HostBudget({
        requestsPerSecond: 1,
        burst: 5,
        maxConcurrent: 6,
        breakerFailures: 5,
        breakerCooldownMs: 60_000,
        breakerMaxCooldownMs: 3_600_000,
        maxTrackedRegistrableDomains: 20_000,
        maxTrackedOrigins: 20_000,
        random: () => 0,
    })
    const runner = new FetchRunner(
        { fetch } as ImageFetcher,
        budget,
        scheduler,
        { createPass } as unknown as ConfigurationPolicyService,
        options,
        { createRepublishBatch, publishImage } as unknown as FrontierPublisher
    )
    return { runner, fetch, check, createPass, republish, publishImage }
}

describe('FetchRunner', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(NOW_MS))
    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('passes cached validators and TDM state to the image request', async () => {
        const harness = build({}, { tdmrepReservation: true })
        const cache: HttpCacheMetadata = {
            requestTimeMs: NOW_MS - 10,
            responseTimeMs: NOW_MS,
            etag: '"image-v1"',
        }
        const stored = new Map<string, CrawlHistoryItem>([
            [
                candidate().originalRef,
                {
                    kind: 'url',
                    key: candidate().originalRef,
                    nextFetchAtMs: NOW_MS,
                    storageExpiresAtMs: NOW_MS,
                    outcome: 'ok',
                    cache,
                },
            ],
        ])

        await harness.runner.run([candidate()], stored)

        expect(harness.fetch.mock.calls[0][1]).toMatchObject({
            maxBytes: OPTIONS.maxBytes,
            maxRedirects: OPTIONS.maxRedirects,
            cache,
            tdmrepReservation: true,
        })
    })

    it('publishes an accepted image and records a terminal URL result', async () => {
        const bytes = Buffer.from('image')
        const harness = build({ bytes, contentType: 'image/png' })

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(harness.publishImage).toHaveBeenCalledWith(
            expect.objectContaining({ originalRef: candidate().originalRef }),
            expect.objectContaining({ bytes })
        )
        expect(attempt).toMatchObject({
            outcome: 'ok',
            finished: true,
            lost: false,
            history: { kind: 'url', key: candidate().originalRef, nextFetchAtMs: NOW_MS + 30 * 24 * 60 * 60 * 1000 },
        })
    })

    it('uses one worker limit across sibling origins', async () => {
        const harness = build({}, {}, 'queued', { ...OPTIONS, maxConcurrentPerRegistrableDomain: 1 })
        let releaseFirst: (() => void) | undefined
        harness.fetch.mockImplementationOnce(
            (url: string) =>
                new Promise<ImageFetchResult>((resolve) => {
                    releaseFirst = () => resolve({ outcome: 'ok', redirects: 0, currentUrl: url })
                })
        )
        const sibling = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://images.example.com/b.png',
            host: 'images.example.com',
            origin: 'https://images.example.com',
        })

        const run = harness.runner.run([candidate(), sibling], new Map())
        await Promise.resolve()
        await Promise.resolve()

        expect(harness.fetch).toHaveBeenCalledTimes(1)
        expect(releaseFirst).toBeDefined()
        releaseFirst?.()
        await run
        expect(harness.fetch).toHaveBeenCalledTimes(2)
    })

    it('does not let one origin occupy every registrable-domain worker', async () => {
        const harness = build({}, {}, 'queued', { ...OPTIONS, maxConcurrentPerRegistrableDomain: 2 })
        let releaseFirst: (() => void) | undefined
        let releaseSecond: (() => void) | undefined
        harness.fetch
            .mockImplementationOnce(
                (url: string) =>
                    new Promise<ImageFetchResult>((resolve) => {
                        releaseFirst = () => resolve({ outcome: 'ok', redirects: 0, currentUrl: url })
                    })
            )
            .mockImplementationOnce(
                (url: string) =>
                    new Promise<ImageFetchResult>((resolve) => {
                        releaseSecond = () => resolve({ outcome: 'ok', redirects: 0, currentUrl: url })
                    })
            )
        const sameOrigin = candidate({ originalRef: `imageurl:${'b'.repeat(22)}` })
        const siblingOrigin = candidate({
            originalRef: `imageurl:${'c'.repeat(22)}`,
            currentUrl: 'https://images.example.com/c.png',
            host: 'images.example.com',
            origin: 'https://images.example.com',
        })

        const run = harness.runner.run([candidate(), sameOrigin, siblingOrigin], new Map())
        await Promise.resolve()
        await Promise.resolve()

        expect(harness.fetch.mock.calls.map(([url]) => url)).toEqual([candidate().currentUrl, siblingOrigin.currentUrl])
        releaseFirst?.()
        releaseSecond?.()
        await run
        expect(harness.fetch).toHaveBeenCalledTimes(3)
    })

    it('marks an image publish failure as lost after all candidate work settles', async () => {
        const harness = build({ bytes: Buffer.from('image'), contentType: 'image/png' })
        harness.publishImage.mockRejectedValue(new Error('queue full'))

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(attempt).toMatchObject({ outcome: 'publish_failed', finished: false, lost: true })
    })

    it('writes a terminal policy refusal without opening an image socket', async () => {
        const harness = build({}, { allowed: false, transient: false, reason: 'robots_disallow' })

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(harness.fetch).not.toHaveBeenCalled()
        expect(attempt).toMatchObject({ outcome: 'robots_disallow', finished: true })
    })

    it('delays a transient configuration failure without writing URL history', async () => {
        const harness = build({}, { allowed: false, transient: true, reason: 'configuration_unreachable' })

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(harness.republish).toHaveBeenCalledWith(
            candidate(),
            {
                currentUrl: candidate().currentUrl,
                host: candidate().host,
                origin: candidate().origin,
                registrableDomain: candidate().registrableDomain,
            },
            'not_ready',
            3_600_000
        )
        expect(attempt).toMatchObject({ outcome: 'backoff', finished: false, lost: false })
        expect(attempt.history).toBeUndefined()
    })

    it('keeps the effective URL and charges every request before retrying', async () => {
        const harness = build({
            outcome: 'server_error',
            status: 503,
            redirects: 2,
            currentUrl: 'https://cdn.example.com/final.png',
            retryAfterMs: 120_000,
        })
        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(harness.republish).toHaveBeenCalledWith(
            expect.objectContaining({
                currentUrl: 'https://cdn.example.com/final.png',
                remainingHops: MAX_HOPS - 2,
                fetchCount: 3,
            }),
            expect.objectContaining({ currentUrl: 'https://cdn.example.com/final.png' }),
            'retry',
            120_000
        )
        expect(attempt).toMatchObject({ outcome: 'server_error', finished: false })
    })

    it('republishes an unfollowed redirect target with the original ref', async () => {
        const harness = build({
            outcome: 'redirect_offsite',
            status: 302,
            currentUrl: candidate().currentUrl,
            redirectTarget: { url: 'https://img.other.net/a.png', host: 'img.other.net' },
        })

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(harness.republish).toHaveBeenCalledWith(
            expect.objectContaining({ originalRef: candidate().originalRef, fetchCount: 1 }),
            {
                currentUrl: 'https://img.other.net/a.png',
                host: 'img.other.net',
                origin: 'https://img.other.net',
                registrableDomain: 'other.net',
            },
            'redirect',
            0
        )
        expect(attempt).toMatchObject({ outcome: 'redirect_offsite', finished: false })
    })

    it('records a terminal refusal from a same-origin redirect policy check', async () => {
        const harness = build({
            outcome: 'redirect_policy_refused',
            redirects: 1,
            currentUrl: 'https://cdn.example.com/private/a.png',
            refusalReason: 'robots_disallow',
            policyTransient: false,
        })

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(harness.republish).not.toHaveBeenCalled()
        expect(attempt).toMatchObject({
            outcome: 'robots_disallow',
            finished: true,
            candidate: { remainingHops: MAX_HOPS - 1, fetchCount: 1 },
        })
    })

    it('delays a transient same-origin redirect policy failure without spending another hop', async () => {
        const harness = build({
            outcome: 'redirect_policy_refused',
            redirects: 1,
            currentUrl: 'https://cdn.example.com/next/a.png',
            refusalReason: 'configuration_unreachable',
            policyTransient: true,
        })

        await harness.runner.run([candidate()], new Map())

        expect(harness.republish).toHaveBeenCalledWith(
            expect.objectContaining({
                currentUrl: 'https://cdn.example.com/next/a.png',
                remainingHops: MAX_HOPS - 1,
                fetchCount: 1,
            }),
            expect.any(Object),
            'not_ready',
            3_600_000
        )
    })

    it('persists a crawl wait that extends beyond the current pass', async () => {
        const harness = build({
            outcome: 'request_deferred',
            schedulingReason: 'deadline',
            schedulingWaitMs: 600_000,
        })

        await harness.runner.run([candidate()], new Map())

        expect(harness.republish).toHaveBeenCalledWith(expect.any(Object), expect.any(Object), 'not_ready', 600_000)
    })

    it('returns pass-deadline work directly to the frontier', async () => {
        const harness = build({}, {}, 'queued', { ...OPTIONS, batchBudgetMs: -1 })

        await harness.runner.run([candidate()], new Map())

        expect(harness.republish).toHaveBeenCalledWith(expect.any(Object), expect.any(Object), 'pass_deadline', 0)
    })

    it('finishes a retry when its last hop was the failed request', async () => {
        const harness = build({ outcome: 'timeout' })

        const [attempt] = await harness.runner.run([candidate({ remainingHops: 1 })], new Map())

        expect(harness.republish).not.toHaveBeenCalled()
        expect(attempt).toMatchObject({ outcome: HOPS_EXHAUSTED, finished: true })
    })

    it('does not start policy or image requests when the hop budget is empty', async () => {
        const harness = build()

        const [attempt] = await harness.runner.run([candidate({ remainingHops: 0 })], new Map())

        expect(harness.check).not.toHaveBeenCalled()
        expect(harness.fetch).not.toHaveBeenCalled()
        expect(attempt).toMatchObject({ outcome: HOPS_EXHAUSTED, finished: true })
    })

    it('records a terminal refusal when no delay topic can hold the wait', async () => {
        const harness = build({ outcome: 'timeout' }, {}, 'refused_delay')
        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(attempt).toMatchObject({ outcome: DELAY_TOO_LONG, finished: true })
    })

    it('merges a 304 response into the previous cache metadata', async () => {
        const previousCache: HttpCacheMetadata = {
            requestTimeMs: NOW_MS - 2_000,
            responseTimeMs: NOW_MS - 1_000,
            etag: '"v1"',
            lastModified: 'yesterday',
        }
        const harness = build({
            outcome: 'not_modified',
            status: 304,
            cache: { requestTimeMs: NOW_MS - 10, responseTimeMs: NOW_MS, etag: '"v2"' },
        })
        const stored = new Map<string, CrawlHistoryItem>([
            [
                candidate().originalRef,
                {
                    kind: 'url',
                    key: candidate().originalRef,
                    nextFetchAtMs: NOW_MS,
                    storageExpiresAtMs: NOW_MS,
                    outcome: 'ok',
                    cache: previousCache,
                },
            ],
        ])

        const [attempt] = await harness.runner.run([candidate()], stored)

        expect(attempt.history?.cache).toMatchObject({ etag: '"v2"', lastModified: 'yesterday' })
    })

    it('retains validators that a 304 response omits', async () => {
        const previousCache: HttpCacheMetadata = {
            requestTimeMs: NOW_MS - 2_000,
            responseTimeMs: NOW_MS - 1_000,
            etag: '"v1"',
            lastModified: 'yesterday',
        }
        const harness = build({
            outcome: 'not_modified',
            status: 304,
            cache: { requestTimeMs: NOW_MS - 10, responseTimeMs: NOW_MS },
        })
        const stored = new Map<string, CrawlHistoryItem>([
            [
                candidate().originalRef,
                {
                    kind: 'url',
                    key: candidate().originalRef,
                    nextFetchAtMs: NOW_MS,
                    storageExpiresAtMs: NOW_MS,
                    outcome: 'ok',
                    cache: previousCache,
                },
            ],
        ])

        const [attempt] = await harness.runner.run([candidate()], stored)

        expect(attempt.history?.cache).toMatchObject({
            requestTimeMs: NOW_MS - 10,
            responseTimeMs: NOW_MS,
            etag: '"v1"',
            lastModified: 'yesterday',
        })
    })

    it('does not store a redirect target validator under the original URL ref', async () => {
        const harness = build({
            redirects: 1,
            currentUrl: 'https://cdn.example.com/moved.png',
            cache: {
                requestTimeMs: NOW_MS - 10,
                responseTimeMs: NOW_MS,
                etag: '"redirect-target"',
                lastModified: 'today',
                cacheControl: 'max-age=60',
            },
        })

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(attempt.history?.cache).toMatchObject({ cacheControl: 'max-age=60' })
        expect(attempt.history?.cache?.etag).toBeUndefined()
        expect(attempt.history?.cache?.lastModified).toBeUndefined()
    })

    it('extends URL history to the end of explicit freshness', async () => {
        const fortyDaysMs = 40 * 24 * 60 * 60 * 1000
        const harness = build({
            cache: {
                requestTimeMs: NOW_MS,
                responseTimeMs: NOW_MS,
                cacheControl: `s-maxage=${fortyDaysMs / 1000}`,
            },
        })

        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(attempt.history?.nextFetchAtMs).toBe(NOW_MS + fortyDaysMs)
        expect(attempt.history?.storageExpiresAtMs).toBe(NOW_MS + fortyDaysMs)
    })
})
