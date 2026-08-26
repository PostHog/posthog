import { Message } from 'node-rdkafka'

import { FetchCandidate, MAX_HOPS, serializeFrontierRecord } from './collected-urls-record'
import { CrawlHistoryItem, CrawlHistoryStore, configurationCacheKey } from './crawl-history'
import { AttemptOutcome, DELAY_TOO_LONG, FetchAttempt, FetchPass, HOPS_EXHAUSTED } from './fetch-runner'
import { FrontierPublisher, RepublishFlushResult, RepublishResult } from './frontier-publisher'
import { ImageFetchConsumerMetrics, ImageFetchRequestMetrics } from './metrics'
import { UrlFetchConsumer } from './url-fetch-consumer'

const NOW_MS = 1_700_000_000_000

function candidate(name: string, overrides: Partial<FetchCandidate> = {}): FetchCandidate {
    const hash = name.padEnd(22, '0')
    return {
        originalRef: `imageurl:${hash}`,
        currentUrl: `https://cdn.example.com/${name}.png`,
        host: 'cdn.example.com',
        origin: 'https://cdn.example.com',
        registrableDomain: 'example.com',
        remainingHops: MAX_HOPS,
        notBeforeMs: 0,
        firstSeenAtMs: NOW_MS,
        fetchCount: 0,
        republishCount: 0,
        lastRepublishReason: null,
        ...overrides,
    }
}

function message(candidates: FetchCandidate[], key = 'example.com'): Message {
    const value = serializeFrontierRecord(candidates)
    return {
        value,
        key: Buffer.from(key),
        size: value.length,
        topic: 'session_replay_image_fetch',
        partition: 0,
        offset: 0,
    }
}

class FakeCrawlHistory implements CrawlHistoryStore {
    public readonly items = new Map<string, CrawlHistoryItem>()
    public readKeys: string[][] = []
    public writes: CrawlHistoryItem[][] = []
    public readError: Error | undefined
    public writeError: Error | undefined

    read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        this.readKeys.push(keys)
        if (this.readError) {
            return Promise.reject(this.readError)
        }
        return Promise.resolve(
            new Map(keys.flatMap((key) => (this.items.has(key) ? [[key, this.items.get(key)!] as const] : [])))
        )
    }

    write(items: CrawlHistoryItem[]): Promise<void> {
        this.writes.push(items)
        if (this.writeError) {
            return Promise.reject(this.writeError)
        }
        for (const item of items) {
            this.items.set(item.key, item)
        }
        return Promise.resolve()
    }
}

function terminal(candidate: FetchCandidate, outcome: AttemptOutcome = 'ok'): FetchAttempt {
    return {
        candidate,
        outcome,
        finished: true,
        lost: false,
        history: {
            kind: 'url',
            key: candidate.originalRef,
            nextFetchAtMs: NOW_MS + 30 * 24 * 60 * 60 * 1000,
            storageExpiresAtMs: NOW_MS + 30 * 24 * 60 * 60 * 1000,
            outcome,
        },
        configurationUpdates: [],
    }
}

interface Harness {
    consumer: UrlFetchConsumer
    history: FakeCrawlHistory
    run: jest.Mock<Promise<FetchAttempt[]>, [FetchCandidate[], Map<string, CrawlHistoryItem>]>
    republish: jest.Mock<Promise<RepublishResult>, any[]>
    flush: jest.Mock<Promise<RepublishFlushResult>, []>
}

function build(dryRun = false): Harness {
    const history = new FakeCrawlHistory()
    const run = jest.fn((candidates: FetchCandidate[], _stored: Map<string, CrawlHistoryItem>) =>
        Promise.resolve(candidates.map((item) => terminal(item)))
    )
    const republish = jest.fn(() => Promise.resolve('queued' as const))
    const flush = jest.fn(() => Promise.resolve({ failedUrls: 0 }))
    const consumer = new UrlFetchConsumer(
        history,
        { createRepublishBatch: () => ({ republish, flush }) } as unknown as FrontierPublisher,
        { seenTtlSeconds: 30 * 24 * 60 * 60, dryRun },
        dryRun ? undefined : ({ run } as FetchPass)
    )
    return { consumer, history, run, republish, flush }
}

describe('UrlFetchConsumer', () => {
    afterEach(() => jest.restoreAllMocks())

    it.each([Number.NaN, 0, 3_599, 3_600.5])('refuses an invalid crawl-history TTL of %p', (seenTtlSeconds) => {
        expect(
            () =>
                new UrlFetchConsumer(new FakeCrawlHistory(), {} as FrontierPublisher, { seenTtlSeconds, dryRun: true })
        ).toThrow('AI_RESEARCH_IMAGE_FETCH_CRAWL_HISTORY_TTL_SECONDS')
    })

    it('refuses active mode without a fetch pass', () => {
        expect(
            () =>
                new UrlFetchConsumer(new FakeCrawlHistory(), {} as FrontierPublisher, {
                    seenTtlSeconds: 3_600,
                    dryRun: false,
                })
        ).toThrow('fetch runner')
    })

    it('parses dry-run traffic without reading or writing shared state', async () => {
        const harness = build(true)

        await harness.consumer.handleBatch([message([candidate('a')])], NOW_MS)

        expect(harness.history.readKeys).toEqual([])
        expect(harness.history.writes).toEqual([])
    })

    it('bulk reads URL and per-origin configuration keys', async () => {
        const harness = build()

        await harness.consumer.handleBatch([message([candidate('a'), candidate('b')])], NOW_MS)

        expect(harness.history.readKeys).toEqual([
            [
                candidate('a').originalRef,
                candidate('b').originalRef,
                configurationCacheKey(candidate('a').origin, 'robots'),
                configurationCacheKey(candidate('a').origin, 'tdmrep'),
            ],
        ])
        expect(harness.run.mock.calls[0][0]).toEqual([candidate('a'), candidate('b')])
        expect(harness.history.writes[0]).toHaveLength(2)
    })

    it('records distinct origins and registrable domains for the poll batch', async () => {
        const harness = build()
        const observeBatch = jest.spyOn(ImageFetchConsumerMetrics, 'observeBatch')
        const observeBatchDiversity = jest.spyOn(ImageFetchConsumerMetrics, 'observeBatchDiversity')
        const otherExampleOrigin = candidate('b', {
            currentUrl: 'https://img.example.com/b.png',
            host: 'img.example.com',
            origin: 'https://img.example.com',
        })
        const otherRegistrableDomain = candidate('c', {
            currentUrl: 'https://img.other.net/c.png',
            host: 'img.other.net',
            origin: 'https://img.other.net',
            registrableDomain: 'other.net',
        })

        await harness.consumer.handleBatch(
            [message([candidate('a'), otherExampleOrigin]), message([otherRegistrableDomain], 'other.net')],
            NOW_MS
        )

        expect(observeBatch).toHaveBeenCalledWith(3, 2, expect.any(Number))
        expect(observeBatchDiversity).toHaveBeenCalledWith([1, 1, 1], [2, 1])
    })

    it('deduplicates one global ref within the batch', async () => {
        const harness = build()

        await harness.consumer.handleBatch([message([candidate('a')]), message([candidate('a')])], NOW_MS)

        expect(harness.run.mock.calls[0][0]).toEqual([candidate('a')])
    })

    it('keeps the most conservative durable state from duplicate jobs', async () => {
        const harness = build()
        const stale = candidate('a')
        const advanced = candidate('a', {
            currentUrl: 'https://cdn.example.com/moved.png',
            remainingHops: 7,
            firstSeenAtMs: NOW_MS - 5_000,
            fetchCount: 4,
            republishCount: 3,
            lastRepublishReason: 'retry',
        })

        await harness.consumer.handleBatch([message([stale]), message([advanced])], NOW_MS)

        expect(harness.run.mock.calls[0][0]).toEqual([advanced])
    })

    it('keeps a low-origin-diversity marker from either duplicate job', async () => {
        const harness = build()
        const marked = candidate('a', { lowOriginDiversityDeferred: true })

        await harness.consumer.handleBatch([message([candidate('a')]), message([marked])], NOW_MS)

        expect(harness.run.mock.calls[0][0]).toEqual([marked])
    })

    it('keeps the latest not-before time from duplicate jobs', async () => {
        const harness = build()
        const stale = candidate('a')
        const delayed = candidate('a', {
            remainingHops: 9,
            notBeforeMs: NOW_MS + 30_000,
            republishCount: 1,
            lastRepublishReason: 'retry',
        })

        await harness.consumer.handleBatch([message([stale]), message([delayed])], NOW_MS)

        expect(harness.run.mock.calls[0][0]).toEqual([])
        expect(harness.republish).toHaveBeenCalledWith(
            expect.objectContaining({ remainingHops: 9, notBeforeMs: NOW_MS + 30_000 }),
            expect.any(Object),
            'not_ready',
            30_000
        )
    })

    it('skips a URL whose crawl-history interval has not ended', async () => {
        const harness = build()
        harness.history.items.set(candidate('a').originalRef, {
            kind: 'url',
            key: candidate('a').originalRef,
            nextFetchAtMs: NOW_MS + 1,
            storageExpiresAtMs: NOW_MS + 1,
            outcome: 'ok',
        })

        await harness.consumer.handleBatch([message([candidate('a'), candidate('b')])], NOW_MS)

        expect(harness.run.mock.calls[0][0]).toEqual([candidate('b')])
    })

    it('republishes a job that arrives before its durable not-before time', async () => {
        const harness = build()
        const early = candidate('a', { notBeforeMs: NOW_MS + 30_000 })

        await harness.consumer.handleBatch([message([early])], NOW_MS)

        expect(harness.run.mock.calls[0][0]).toEqual([])
        expect(harness.republish).toHaveBeenCalledWith(
            early,
            {
                currentUrl: early.currentUrl,
                host: early.host,
                origin: early.origin,
                registrableDomain: early.registrableDomain,
            },
            'not_ready',
            30_000
        )
        expect(harness.history.writes).toEqual([])
    })

    it('records a terminal refusal when the remaining delay is over one hour', async () => {
        const harness = build()
        harness.republish.mockResolvedValue('refused_delay')
        const early = candidate('a', { notBeforeMs: NOW_MS + 3_600_001 })

        await harness.consumer.handleBatch([message([early])], NOW_MS)

        expect(harness.history.writes[0]).toEqual([
            expect.objectContaining({ kind: 'url', key: early.originalRef, outcome: DELAY_TOO_LONG }),
        ])
    })

    it('records a terminal refusal when a delayed job has no remaining hops', async () => {
        const harness = build()
        const early = candidate('a', { notBeforeMs: NOW_MS + 30_000, remainingHops: 0 })

        await harness.consumer.handleBatch([message([early])], NOW_MS)

        expect(harness.republish).not.toHaveBeenCalled()
        expect(harness.history.writes[0]).toEqual([
            expect.objectContaining({ kind: 'url', key: early.originalRef, outcome: HOPS_EXHAUSTED }),
        ])
    })

    it('throws when a not-ready republish delivery fails', async () => {
        const harness = build()
        harness.flush.mockResolvedValue({ failedUrls: 1 })
        const early = candidate('a', { notBeforeMs: NOW_MS + 30_000 })

        await expect(harness.consumer.handleBatch([message([early])], NOW_MS)).rejects.toThrow('account for 1 URLs')
        expect(harness.history.writes).toEqual([])
    })

    it('records a retry cause after the republish batch is durable', async () => {
        const harness = build()
        const retryCause = jest.spyOn(ImageFetchRequestMetrics, 'incRetryCause').mockImplementation()
        harness.run.mockImplementation((candidates) =>
            Promise.resolve(
                candidates.map((item) => ({
                    candidate: item,
                    outcome: 'server_error',
                    finished: false,
                    lost: false,
                    configurationUpdates: [],
                }))
            )
        )

        await harness.consumer.handleBatch([message([candidate('a')])], NOW_MS)

        expect(retryCause).toHaveBeenCalledWith('server_error')
    })

    it('does not record a retry cause when the republish batch fails', async () => {
        const harness = build()
        const retryCause = jest.spyOn(ImageFetchRequestMetrics, 'incRetryCause').mockImplementation()
        harness.flush.mockResolvedValue({ failedUrls: 1 })
        harness.run.mockImplementation((candidates) =>
            Promise.resolve(
                candidates.map((item) => ({
                    candidate: item,
                    outcome: 'server_error',
                    finished: false,
                    lost: false,
                    configurationUpdates: [],
                }))
            )
        )

        await expect(harness.consumer.handleBatch([message([candidate('a')])], NOW_MS)).rejects.toThrow(
            'account for 1 URLs'
        )
        expect(retryCause).not.toHaveBeenCalled()
    })

    it('drops a malformed record without running the fetch pass', async () => {
        const harness = build()
        const invalid = message([candidate('a')])
        invalid.value = Buffer.from('{')

        await expect(harness.consumer.handleBatch([invalid], NOW_MS)).resolves.toBeUndefined()
        expect(harness.run).not.toHaveBeenCalled()
    })

    it('rejects a whole multi-job record when one job belongs to another partition', async () => {
        const harness = build()
        const foreign = candidate('foreign', {
            currentUrl: 'https://img.other.net/foreign.png',
            host: 'img.other.net',
            origin: 'https://img.other.net',
            registrableDomain: 'other.net',
        })

        await harness.consumer.handleBatch([message([candidate('a'), foreign])], NOW_MS)

        expect(harness.run).not.toHaveBeenCalled()
        expect(harness.history.readKeys).toEqual([])
    })

    it('throws when the bulk read fails', async () => {
        const harness = build()
        harness.history.readError = new Error('read failed')
        const observeBatch = jest.spyOn(ImageFetchConsumerMetrics, 'observeBatch')
        const observeStoreDuration = jest.spyOn(ImageFetchConsumerMetrics, 'observeStoreDuration')
        const startBatch = jest.spyOn(ImageFetchConsumerMetrics, 'startBatch')
        const finishBatch = jest.spyOn(ImageFetchConsumerMetrics, 'finishBatch')

        await expect(harness.consumer.handleBatch([message([candidate('a')])], NOW_MS)).rejects.toThrow('read failed')
        expect(observeBatch).toHaveBeenCalledWith(1, 1, expect.any(Number))
        expect(observeStoreDuration).toHaveBeenCalledWith('read', 'error', expect.any(Number))
        expect(startBatch).toHaveBeenCalledTimes(1)
        expect(finishBatch).toHaveBeenCalledTimes(1)
    })

    it('throws when the final bulk write fails', async () => {
        const harness = build()
        harness.history.writeError = new Error('write failed')

        await expect(harness.consumer.handleBatch([message([candidate('a')])], NOW_MS)).rejects.toThrow('write failed')
        expect(harness.flush).not.toHaveBeenCalled()
    })

    it('writes durable state before it flushes buffered republishes', async () => {
        const harness = build()
        const order: string[] = []
        harness.run.mockImplementation((candidates) => {
            order.push('published')
            return Promise.resolve(candidates.map((item) => terminal(item)))
        })
        const write = harness.history.write.bind(harness.history)
        harness.history.write = async (items) => {
            order.push('history')
            await write(items)
        }
        harness.flush.mockImplementation(() => {
            order.push('republished')
            return Promise.resolve({ failedUrls: 0 })
        })

        await harness.consumer.handleBatch([message([candidate('a')])], NOW_MS)

        expect(order).toEqual(['published', 'history', 'republished'])
    })

    it('throws when the fetch pass reports a lost URL', async () => {
        const harness = build()
        harness.run.mockImplementation((candidates) =>
            Promise.resolve(
                candidates.map((item) => ({
                    candidate: item,
                    outcome: 'timeout',
                    finished: false,
                    lost: true,
                    configurationUpdates: [],
                }))
            )
        )

        await expect(harness.consumer.handleBatch([message([candidate('a')])], NOW_MS)).rejects.toThrow(
            'account for 1 URLs'
        )
    })
})
