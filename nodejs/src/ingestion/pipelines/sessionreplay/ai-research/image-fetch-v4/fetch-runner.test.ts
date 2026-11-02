import { S3ServiceException } from '@aws-sdk/client-s3'
import { createHash } from 'node:crypto'

import { logger } from '~/common/utils/logger'
import { RecordedTopHogMetric, createRecordingTopHog } from '~/tests/helpers/tophog'

import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { ConfigurationPolicyService, OriginPolicyDecision } from './configuration-policy'
import { ConfigurationCacheItem, CrawlHistoryItem, HttpCacheMetadata } from './crawl-history'
import { DELAY_TOO_LONG, FetchRunner, FetchRunnerOptions, HOPS_EXHAUSTED, URL_TOO_OLD } from './fetch-runner'
import { FrontierPublisher, RepublishResult } from './frontier-publisher'
import { HostBudget } from './host-budget'
import { ImageFetchOptions, ImageFetchResult, ImageFetcher } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'
import { OriginRequestScheduler } from './origin-request-scheduler'
import { ResponseUrlBinding } from './response-url-binding'
import { ImageFetchTopHogMetrics } from './tophog-metrics'

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
const POOL_OPTIONS: FetchRunnerOptions = {
    ...OPTIONS,
    continuousPool: { refillRunnableUrls: 100, maxQueuedUrlsPerOwner: 1_000 },
}
const builtRunners: FetchRunner[] = []
const bind: ResponseUrlBinding = (url) => createHash('sha256').update(url).digest('base64url').slice(0, 22)

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
    budget: HostBudget
    fetch: jest.Mock<Promise<ImageFetchResult>, [string, ImageFetchOptions]>
    check: jest.Mock<Promise<OriginPolicyDecision>, [string, Map<string, ConfigurationCacheItem>, number]>
    createPass: jest.Mock
    republish: jest.Mock<Promise<RepublishResult>, any[]>
    publishImage: jest.Mock<Promise<void>, any[]>
    topHogRecords: Map<string, RecordedTopHogMetric[]>
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
    const recordingTopHog = createRecordingTopHog()
    const runner = new FetchRunner(
        { fetch } as ImageFetcher,
        budget,
        scheduler,
        { createPass } as unknown as ConfigurationPolicyService,
        options,
        { createRepublishBatch } as unknown as FrontierPublisher,
        { refreshIntervalMs: 7 * 24 * 60 * 60 * 1000, publishImage, refreshImage: () => Promise.resolve(true) },
        { bindingFor: () => Promise.resolve(bind) },
        new ImageFetchTopHogMetrics(recordingTopHog.registry)
    )
    builtRunners.push(runner)
    return { runner, budget, fetch, check, createPass, republish, publishImage, topHogRecords: recordingTopHog.records }
}

describe('FetchRunner', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(NOW_MS))
    afterEach(async () => {
        await Promise.all(builtRunners.splice(0).map((runner) => runner.close()))
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('passes cached validators and TDM state to the image request', async () => {
        const harness = build({}, { tdmrepReservation: true })
        const cache: HttpCacheMetadata = {
            requestTimeMs: NOW_MS - 10,
            responseTimeMs: NOW_MS,
            responseUrlHmac: bind(candidate().currentUrl),
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

        await harness.runner.run([candidate({ sourcePartitions: [7, 42] })], stored)

        expect(harness.fetch.mock.calls[0][1]).toMatchObject({
            maxBytes: OPTIONS.maxBytes,
            maxRedirects: OPTIONS.maxRedirects,
            sourcePartitions: [7, 42],
            cache,
            tdmrepReservation: true,
        })
    })

    it.each([
        ['another URL', bind('https://other.example.net/a.png')],
        ['no URL', undefined],
    ])('sends no validator that %s issued, and binds the response to the URL that sent it', async (_name, binding) => {
        const harness = build({ cache: { requestTimeMs: NOW_MS - 10, responseTimeMs: NOW_MS, etag: '"image-v2"' } })
        const stored = new Map<string, CrawlHistoryItem>([
            [
                candidate().originalRef,
                {
                    kind: 'url',
                    key: candidate().originalRef,
                    nextFetchAtMs: NOW_MS,
                    storageExpiresAtMs: NOW_MS,
                    outcome: 'ok',
                    cache: {
                        requestTimeMs: NOW_MS - 10,
                        responseTimeMs: NOW_MS,
                        responseUrlHmac: binding,
                        etag: '"v1"',
                    },
                },
            ],
        ])

        const [attempt] = await harness.runner.run([candidate()], stored)

        expect(harness.fetch.mock.calls[0][1].cache).toBeUndefined()
        expect(attempt.history?.cache).toMatchObject({
            responseUrlHmac: bind(candidate().currentUrl),
            etag: '"image-v2"',
        })
    })

    it.each([
        ['a fetch pass', OPTIONS],
        ['the pod candidate pool', POOL_OPTIONS],
    ])('publishes an accepted image and records a terminal URL result through %s', async (_mode, options) => {
        const bytes = Buffer.from('image')
        const harness = build({ bytes, contentType: 'image/png' }, {}, 'queued', options)

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
        const first = candidate({ sourcePartitions: [110] })
        const sibling = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://images.example.com/b.png',
            host: 'images.example.com',
            origin: 'https://images.example.com',
            sourcePartitions: [110],
        })

        const run = harness.runner.run([first, sibling], new Map())
        await jest.advanceTimersByTimeAsync(0)

        expect(harness.fetch).toHaveBeenCalledTimes(1)
        expect(releaseFirst).toBeDefined()
        releaseFirst?.()
        await run
        expect(harness.fetch).toHaveBeenCalledTimes(2)
        expect(harness.topHogRecords.get('ai_research_v4_image_fetch_block_events_by_registrable_domain')).toEqual([
            {
                key: { registrable_domain: 'example.com', reason: 'domain_concurrency', partition: '110' },
                value: 1,
            },
        ])
    })

    it('starts the next request for a registrable domain while an earlier image publish waits', async () => {
        const harness = build({ bytes: Buffer.from('image'), contentType: 'image/png' }, {}, 'queued', {
            ...OPTIONS,
            maxConcurrentPerRegistrableDomain: 1,
        })
        let releasePublish: () => void = () => undefined
        harness.publishImage.mockImplementationOnce(
            () =>
                new Promise<void>((resolve) => {
                    releasePublish = resolve
                })
        )
        const second = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://cdn.example.com/b.png',
        })

        let passFinished = false
        const run = harness.runner.run([candidate(), second], new Map()).finally(() => {
            passFinished = true
        })
        await jest.advanceTimersByTimeAsync(0)

        expect(harness.fetch.mock.calls.map(([url]) => url)).toEqual([candidate().currentUrl, second.currentUrl])
        expect(passFinished).toBe(false)
        releasePublish()
        const attempts = await run
        expect(attempts.map((attempt) => [attempt.candidate.originalRef, attempt.outcome, attempt.lost])).toEqual(
            expect.arrayContaining([
                [candidate().originalRef, 'ok', false],
                [second.originalRef, 'ok', false],
            ])
        )
        expect(attempts).toHaveLength(2)
    })

    it('allocates sibling-origin workers by queue share', async () => {
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
        await jest.advanceTimersByTimeAsync(0)

        expect(harness.fetch.mock.calls.map(([url]) => url)).toEqual([candidate().currentUrl, siblingOrigin.currentUrl])
        releaseFirst?.()
        releaseSecond?.()
        await run
        expect(harness.fetch).toHaveBeenCalledTimes(3)
    })

    it('records initial capacity after live pod and registrable-domain limits', async () => {
        const observeCapacity = jest
            .spyOn(ImageFetchRequestMetrics, 'observeBatchSchedulableCapacity')
            .mockImplementation()
        const harness = build({}, {}, 'queued', {
            ...OPTIONS,
            maxConcurrentPerRegistrableDomain: 2,
            maxInFlightRequests: 3,
        })
        const candidates = [
            candidate({ sourcePartitions: [110] }),
            ...Array.from({ length: 2 }, (_, index) =>
                candidate({
                    originalRef: `imageurl:${String(index + 1).repeat(22)}`,
                    currentUrl: `https://cdn.example.com/image-${index}.png`,
                    sourcePartitions: [110],
                })
            ),
            ...Array.from({ length: 2 }, (_, index) =>
                candidate({
                    originalRef: `imageurl:${String(index + 3).repeat(22)}`,
                    currentUrl: `https://origin-${index}.other.net/image.png`,
                    host: `origin-${index}.other.net`,
                    origin: `https://origin-${index}.other.net`,
                    registrableDomain: 'other.net',
                    sourcePartitions: [42],
                })
            ),
        ]
        const grant = harness.budget.take('example.com', 'https://cdn.example.com', NOW_MS, NOW_MS + 10_000, true)
        expect(grant).toMatchObject({ granted: true, waitMs: 0 })
        expect(harness.budget.acquireConnection('example.com', 'https://cdn.example.com')).toBe(true)
        harness.budget.markRequestStarted(
            'example.com',
            'https://cdn.example.com',
            NOW_MS,
            grant.granted ? grant.reservedStartAtMs : null,
            'configuration'
        )

        await harness.runner.run(candidates, new Map())

        expect(observeCapacity).toHaveBeenCalledWith(3, 3)
        expect(harness.topHogRecords.get('ai_research_v4_image_fetch_block_events_by_registrable_domain')).toEqual([
            {
                key: { registrable_domain: 'example.com', reason: 'domain_concurrency', partition: '110' },
                value: 2,
            },
        ])
        harness.budget.releaseConnection('example.com', 'https://cdn.example.com')
    })

    it('keeps one request slot on the largest origin queue', async () => {
        const harness = build({}, {}, 'queued', {
            ...OPTIONS,
            maxConcurrentPerRegistrableDomain: 1,
            maxInFlightRequests: 1,
        })
        const small = candidate({
            currentUrl: 'https://small.example.com/a.png',
            host: 'small.example.com',
            origin: 'https://small.example.com',
        })
        const largeFirst = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://large.example.com/a.png',
            host: 'large.example.com',
            origin: 'https://large.example.com',
        })
        const largeSecond = candidate({
            originalRef: `imageurl:${'c'.repeat(22)}`,
            currentUrl: 'https://large.example.com/b.png',
            host: 'large.example.com',
            origin: 'https://large.example.com',
        })

        await harness.runner.run([small, largeFirst, largeSecond], new Map())

        expect(harness.fetch.mock.calls.map(([url]) => url)).toEqual([
            largeFirst.currentUrl,
            largeSecond.currentUrl,
            small.currentUrl,
        ])
    })

    it('processes a low-capacity tail instead of republishing it for more diversity', async () => {
        const harness = build({}, {}, 'queued', {
            ...OPTIONS,
            maxInFlightRequests: 1,
        })
        const candidates = Array.from({ length: 4 }, (_, index) => {
            const origin = `https://cdn-${index}.example.com`
            return candidate({
                originalRef: `imageurl:${index.toString().padStart(22, '0')}`,
                currentUrl: `${origin}/${index}.png`,
                host: `cdn-${index}.example.com`,
                origin,
            })
        })

        const attempts = await harness.runner.run(candidates, new Map())

        expect(harness.fetch).toHaveBeenCalledTimes(4)
        expect(harness.republish).not.toHaveBeenCalled()
        expect(attempts).toHaveLength(4)
    })

    it('keeps the pod request limit across overlapping passes', async () => {
        const observeCapacity = jest
            .spyOn(ImageFetchRequestMetrics, 'observeBatchSchedulableCapacity')
            .mockImplementation()
        const harness = build({}, {}, 'queued', { ...OPTIONS, maxInFlightRequests: 1 })
        const releases: Array<() => void> = []
        let signalSecondFetchStarted: () => void = () => undefined
        const secondFetchStarted = new Promise<void>((resolve) => {
            signalSecondFetchStarted = resolve
        })
        harness.fetch.mockImplementation(
            (url: string) =>
                new Promise<ImageFetchResult>((resolve) => {
                    releases.push(() => resolve({ outcome: 'ok', redirects: 0, currentUrl: url }))
                    if (releases.length === 2) {
                        signalSecondFetchStarted()
                    }
                })
        )
        const otherDomain = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://cdn.other.net/b.png',
            host: 'cdn.other.net',
            origin: 'https://cdn.other.net',
            registrableDomain: 'other.net',
        })

        const firstRun = harness.runner.run([candidate()], new Map())
        const secondRun = harness.runner.run([otherDomain], new Map())
        await jest.advanceTimersByTimeAsync(0)

        expect(harness.fetch).toHaveBeenCalledTimes(1)
        expect(observeCapacity.mock.calls).toEqual([
            [1, 1],
            [0, 1],
        ])
        releases[0]()
        await secondFetchStarted
        expect(harness.fetch).toHaveBeenCalledTimes(2)
        releases[1]()
        await Promise.all([firstRun, secondRun])
    })

    it('finishes a pooled batch with queued candidates before close stops the pool', async () => {
        const harness = build({}, {}, 'queued', { ...POOL_OPTIONS, maxInFlightRequests: 1 })
        let releaseFirst: () => void = () => undefined
        harness.fetch.mockImplementationOnce(
            (url: string) =>
                new Promise<ImageFetchResult>((resolve) => {
                    releaseFirst = () => resolve({ outcome: 'ok', redirects: 0, currentUrl: url })
                })
        )
        const queued = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://cdn.other.net/b.png',
            host: 'cdn.other.net',
            origin: 'https://cdn.other.net',
            registrableDomain: 'other.net',
        })

        const run = harness.runner.run([candidate(), queued], new Map())
        await jest.advanceTimersByTimeAsync(0)
        let closed = false
        const close = harness.runner.close().then(() => {
            closed = true
        })
        await jest.advanceTimersByTimeAsync(0)
        expect(closed).toBe(false)
        releaseFirst()
        await jest.advanceTimersByTimeAsync(0)

        expect((await run).map((attempt) => attempt.candidate.currentUrl)).toEqual([
            candidate().currentUrl,
            queued.currentUrl,
        ])
        await close
    })

    it('shares one registrable domain limit between batches in the pod candidate pool', async () => {
        const harness = build({}, {}, 'queued', POOL_OPTIONS)
        const releases: Array<() => void> = []
        harness.fetch.mockImplementation(
            (url: string) =>
                new Promise<ImageFetchResult>((resolve) => {
                    releases.push(() => resolve({ outcome: 'ok', redirects: 0, currentUrl: url }))
                })
        )
        const onOrigin = (label: string): FetchCandidate =>
            candidate({
                originalRef: `imageurl:${label.repeat(22)}`,
                currentUrl: `https://${label}.example.com/a.png`,
                host: `${label}.example.com`,
                origin: `https://${label}.example.com`,
            })

        const firstBatch = harness.runner.run([onOrigin('a'), onOrigin('b')], new Map())
        const secondBatch = harness.runner.run([onOrigin('c'), onOrigin('d')], new Map())
        await jest.advanceTimersByTimeAsync(0)

        expect(harness.fetch).toHaveBeenCalledTimes(2)
        releases.splice(0).forEach((release) => release())
        await jest.advanceTimersByTimeAsync(0)
        expect(harness.fetch).toHaveBeenCalledTimes(4)
        releases.splice(0).forEach((release) => release())
        await Promise.all([firstBatch, secondBatch])
    })

    it('does not start a queued request after another worker aborts its pass', async () => {
        const harness = build({}, {}, 'queued', { ...OPTIONS, maxInFlightRequests: 2 })
        let releaseBlocker: () => void = () => undefined
        let signalBlockerStarted: () => void = () => undefined
        const blockerStarted = new Promise<void>((resolve) => {
            signalBlockerStarted = resolve
        })
        harness.fetch.mockImplementation((url: string) => {
            if (url.includes('blocker')) {
                signalBlockerStarted()
                return new Promise<ImageFetchResult>((resolve) => {
                    releaseBlocker = () => resolve({ outcome: 'ok', redirects: 0, currentUrl: url })
                })
            }
            if (url.includes('failure')) {
                return Promise.reject(new Error('dependency unavailable'))
            }
            return Promise.resolve({ outcome: 'ok', redirects: 0, currentUrl: url })
        })
        const blocker = candidate({ currentUrl: 'https://blocker.example.com/a.png' })
        const failure = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://failure.example.com/b.png',
            host: 'failure.example.com',
            origin: 'https://failure.example.com',
        })
        const mustNotStart = candidate({
            originalRef: `imageurl:${'c'.repeat(22)}`,
            currentUrl: 'https://queued.example.com/c.png',
            host: 'queued.example.com',
            origin: 'https://queued.example.com',
        })

        const blockingRun = harness.runner.run([blocker], new Map())
        await blockerStarted
        const failingRun = harness.runner.run([failure, mustNotStart], new Map())

        await expect(failingRun).rejects.toThrow('dependency unavailable')
        expect(harness.fetch.mock.calls.map(([url]) => url)).toEqual([blocker.currentUrl, failure.currentUrl])
        releaseBlocker()
        await blockingRun
    })

    it.each([
        ['a fetch pass', OPTIONS],
        ['the pod candidate pool', POOL_OPTIONS],
    ])('stops taking queue work after a fatal candidate error in %s', async (_mode, options) => {
        const harness = build({}, {}, 'queued', { ...options, maxInFlightRequests: 1 })
        harness.fetch.mockRejectedValueOnce(new Error('dependency unavailable'))
        const second = candidate({ originalRef: `imageurl:${'b'.repeat(22)}` })

        await expect(harness.runner.run([candidate(), second], new Map())).rejects.toThrow('dependency unavailable')

        expect(harness.fetch).toHaveBeenCalledTimes(1)
    })

    it('deduplicates canonical refs before queue scheduling', async () => {
        const harness = build()
        const duplicate = candidate({ republishCount: 1, lastRepublishReason: 'retry' })

        const attempts = await harness.runner.run([candidate(), duplicate], new Map())

        expect(harness.fetch).toHaveBeenCalledTimes(1)
        expect(attempts).toHaveLength(1)
        expect(attempts[0].candidate).toMatchObject({ republishCount: 1, lastRepublishReason: 'retry' })
    })

    it.each([
        ['a fetch pass', OPTIONS],
        ['the pod candidate pool', POOL_OPTIONS],
    ])('retries an image publish failure through the frontier in %s', async (_mode, options) => {
        const harness = build({ bytes: Buffer.from('image'), contentType: 'image/png' }, {}, 'queued', options)
        harness.publishImage.mockRejectedValue(
            new S3ServiceException({
                name: 'SlowDown',
                $fault: 'server',
                $metadata: { httpStatusCode: 503 },
                message: 'images/url/month=2026-10/7/secret-key',
            })
        )
        const warn = jest.spyOn(logger, 'warn')

        const attempts = await harness.runner.run(
            [candidate(), candidate({ originalRef: `imageurl:${'b'.repeat(22)}` })],
            new Map()
        )

        expect(attempts).toEqual([
            expect.objectContaining({ outcome: 'publish_failed', finished: false, lost: false }),
            expect.objectContaining({ outcome: 'publish_failed', finished: false, lost: false }),
        ])
        expect(harness.republish).toHaveBeenCalledTimes(2)
        expect(harness.republish).toHaveBeenCalledWith(
            expect.objectContaining({ lastBlockReason: 'transient_backoff' }),
            expect.any(Object),
            'retry',
            60_000
        )
        // One log for the burst, with the error name and status and nothing that names the image.
        const logged = warn.mock.calls.filter(([, event]) => event === 'ai_research_v4_image_fetch_storage_failed')
        expect(logged).toEqual([
            [
                '🌐',
                'ai_research_v4_image_fetch_storage_failed',
                { operation: 'publish', error: 'SlowDown', code: undefined, httpStatusCode: 503, failures: 1 },
            ],
        ])
        warn.mockRestore()
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
            expect.objectContaining({
                originalRef: candidate().originalRef,
                lastBlockReason: 'configuration_unreachable',
            }),
            {
                currentUrl: candidate().currentUrl,
                host: candidate().host,
                origin: candidate().origin,
                registrableDomain: candidate().registrableDomain,
            },
            'not_ready',
            3_600_000
        )
        expect(attempt).toMatchObject({
            outcome: 'backoff',
            finished: false,
            lost: false,
            block: { reason: 'configuration_unreachable', waitMs: 3_600_000 },
        })
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
        expect(attempt).toMatchObject({
            outcome: 'server_error',
            finished: false,
            block: { reason: 'retry_after', waitMs: 120_000 },
        })
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

    it.each<[string, FetchRunnerOptions, 'none' | 'transient' | 'retry_after_1h', string, number]>([
        ['returns pass-deadline work directly to the frontier from a fetch pass', OPTIONS, 'none', 'pass_deadline', 0],
        [
            'returns pass-deadline work directly to the frontier from the pod pool',
            POOL_OPTIONS,
            'none',
            'pass_deadline',
            0,
        ],
        [
            'delays pass-deadline work of a backed-off domain from a fetch pass',
            OPTIONS,
            'transient',
            'not_ready',
            60_000,
        ],
        [
            'delays pass-deadline work of a backed-off domain from the pod pool',
            POOL_OPTIONS,
            'transient',
            'not_ready',
            60_000,
        ],
        [
            'holds pass-deadline work of a long back-off in the ten-minute tier',
            OPTIONS,
            'retry_after_1h',
            'not_ready',
            600_000,
        ],
    ])('%s', async (_name, options, backOff, reason, waitMs) => {
        const harness = build({}, {}, 'queued', { ...options, batchBudgetMs: -1 })
        if (backOff !== 'none') {
            harness.budget.recordTransientFailure(
                'example.com',
                NOW_MS,
                backOff === 'retry_after_1h' ? 3_600_000 : undefined
            )
        }

        await harness.runner.run([candidate()], new Map())

        expect(harness.fetch).not.toHaveBeenCalled()
        expect(harness.republish).toHaveBeenCalledWith(expect.any(Object), expect.any(Object), reason, waitMs)
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

    it.each([
        ['no delay topic can hold the wait', 'refused_delay', DELAY_TOO_LONG],
        ['the URL is past the age limit', 'refused_age', URL_TOO_OLD],
    ] as const)('records a terminal refusal when %s', async (_name, republishResult, outcome) => {
        const harness = build({ outcome: 'timeout' }, {}, republishResult)
        const [attempt] = await harness.runner.run([candidate()], new Map())

        expect(attempt).toMatchObject({ outcome, finished: true, history: { outcome } })
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
