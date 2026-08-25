import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'

import {
    FetchCandidate,
    MAX_HOPS,
    MAX_JOBS_PER_RECORD,
    MAX_RECORD_BYTES,
    parseCollectedUrlsRecord,
} from './collected-urls-record'
import { FrontierPublisher, RepublishBatch } from './frontier-publisher'
import { ImageFetchResult } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'

const FRONTIER = 'session_replay_image_fetch'
const SCRUB = 'session_replay_image_scrub'
const TIERS = [
    { topic: 'retry_1m', delayMs: 60_000, metricTopic: 'retry_1m' as const },
    { topic: 'retry_10m', delayMs: 600_000, metricTopic: 'retry_10m' as const },
    { topic: 'retry_1h', delayMs: 3_600_000, metricTopic: 'retry_1h' as const },
]

function candidate(overrides: Partial<FetchCandidate> = {}): FetchCandidate {
    return {
        originalRef: `imageurl:${'a'.repeat(22)}`,
        currentUrl: 'https://cdn.example.com/a.png',
        host: 'cdn.example.com',
        origin: 'https://cdn.example.com',
        registrableDomain: 'example.com',
        remainingHops: MAX_HOPS,
        notBeforeMs: 0,
        firstSeenAtMs: 1_700_000_000_000,
        fetchCount: 0,
        republishCount: 0,
        lastRepublishReason: null,
        ...overrides,
    }
}

interface SentMessage {
    topic: string
    key: string
    value: Buffer
    headers?: Record<string, string>
}

function build(): {
    publisher: FrontierPublisher
    batch: RepublishBatch
    sent: SentMessage[]
} {
    const sent: SentMessage[] = []
    const producer = {
        produce: (message: { topic: string; key: Buffer; value: Buffer; headers?: Record<string, string> }) => {
            sent.push({ ...message, key: message.key.toString() })
            return Promise.resolve()
        },
    } as unknown as KafkaProducerWrapper
    const publisher = new FrontierPublisher(producer, {
        frontierTopic: FRONTIER,
        scrubTopic: SCRUB,
        delayTiers: TIERS,
        maxConcurrentImagePublishes: 2,
        maxConcurrentRepublishes: 2,
    })
    return { publisher, batch: publisher.createRepublishBatch(), sent }
}

describe('FrontierPublisher', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(1_700_000_000_000))
    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('groups frontier redirects by target registrable domain', async () => {
        const { batch, sent } = build()
        const republished = jest.spyOn(ImageFetchRequestMetrics, 'incRepublished').mockImplementation()
        const target = {
            currentUrl: 'https://img.other.net/a.png',
            host: 'img.other.net',
            origin: 'https://img.other.net',
            registrableDomain: 'other.net',
        }

        expect(await batch.republish(candidate(), target, 'redirect')).toBe('queued')
        expect(
            await batch.republish(candidate({ originalRef: `imageurl:${'b'.repeat(22)}` }), target, 'redirect')
        ).toBe('queued')
        expect(sent).toEqual([])
        await expect(batch.flush()).resolves.toEqual({ failedUrls: 0 })

        expect(republished).toHaveBeenCalledTimes(2)
        expect(sent).toHaveLength(1)
        expect(sent[0]).toMatchObject({ topic: FRONTIER, key: 'other.net' })
        expect(parseCollectedUrlsRecord(sent[0].value, 'other.net')).toMatchObject({
            ok: true,
            candidates: [
                {
                    originalRef: `imageurl:${'a'.repeat(22)}`,
                    currentUrl: 'https://img.other.net/a.png',
                    remainingHops: MAX_HOPS - 1,
                    republishCount: 1,
                    lastRepublishReason: 'redirect',
                },
                { originalRef: `imageurl:${'b'.repeat(22)}` },
            ],
        })
    })

    it.each([
        ['an unspecified retry', 0, 'retry_1m', 60_000],
        ['a short retry', 30_000, 'retry_1m', 60_000],
        ['a medium retry', 120_000, 'retry_10m', 600_000],
        ['a long supported retry', 3_600_000, 'retry_1h', 3_600_000],
    ])('parks %s once in the smallest sufficient delay topic', async (_name, waitMs, topic, delayMs) => {
        const { batch, sent } = build()
        const republished = jest.spyOn(ImageFetchRequestMetrics, 'incRepublished').mockImplementation()

        expect(await batch.republish(candidate(), candidate(), 'retry', waitMs)).toBe('queued')
        await batch.flush()

        expect(republished).toHaveBeenCalledWith('retry', 'delay')
        expect(sent[0].topic).toBe(topic)
        expect(parseCollectedUrlsRecord(sent[0].value, 'example.com')).toMatchObject({
            ok: true,
            candidates: [{ notBeforeMs: 1_700_000_000_000 + delayMs }],
        })
    })

    it('groups delayed jobs by destination topic and registrable domain', async () => {
        const { batch, sent } = build()
        const second = candidate({ originalRef: `imageurl:${'b'.repeat(22)}` })
        const other = candidate({
            originalRef: `imageurl:${'c'.repeat(22)}`,
            currentUrl: 'https://img.other.net/c.png',
            host: 'img.other.net',
            origin: 'https://img.other.net',
            registrableDomain: 'other.net',
        })

        await batch.republish(candidate(), candidate(), 'retry', 30_000)
        await batch.republish(second, second, 'not_ready', 30_000)
        await batch.republish(other, other, 'retry', 30_000)
        await batch.flush()

        expect(sent).toHaveLength(2)
        const example = sent.find((item) => item.key === 'example.com')!
        expect(example.topic).toBe('retry_1m')
        expect(parseCollectedUrlsRecord(example.value, 'example.com')).toMatchObject({
            ok: true,
            candidates: [{ originalRef: candidate().originalRef }, { originalRef: second.originalRef }],
        })
    })

    it('keeps configured destination topics separate when they share a metric class', async () => {
        const sent: SentMessage[] = []
        const producer = {
            produce: (message: { topic: string; key: Buffer; value: Buffer }) => {
                sent.push({ ...message, key: message.key.toString() })
                return Promise.resolve()
            },
        } as unknown as KafkaProducerWrapper
        const publisher = new FrontierPublisher(producer, {
            frontierTopic: FRONTIER,
            scrubTopic: SCRUB,
            delayTiers: [
                { topic: 'short', delayMs: 60_000, metricTopic: 'retry_1m' },
                { topic: 'long', delayMs: 120_000, metricTopic: 'retry_1m' },
            ],
            maxConcurrentImagePublishes: 2,
            maxConcurrentRepublishes: 2,
        })
        const batch = publisher.createRepublishBatch()

        await batch.republish(candidate(), candidate(), 'not_ready', 30_000)
        await batch.republish(
            candidate({ originalRef: `imageurl:${'b'.repeat(22)}` }),
            candidate(),
            'not_ready',
            90_000
        )
        await batch.flush()

        expect(sent.map((message) => message.topic).sort()).toEqual(['long', 'short'])
    })

    it('records messages, registrable domains, and delivery time for each destination topic', async () => {
        const { batch } = build()
        const observeRepublishBatch = jest.spyOn(ImageFetchRequestMetrics, 'observeRepublishBatch').mockImplementation()
        const observeRepublishFlush = jest.spyOn(ImageFetchRequestMetrics, 'observeRepublishFlush').mockImplementation()
        const other = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://img.other.net/b.png',
            host: 'img.other.net',
            origin: 'https://img.other.net',
            registrableDomain: 'other.net',
        })

        await batch.republish(candidate(), candidate(), 'pass_deadline')
        await batch.republish(other, other, 'retry', 30_000)
        await batch.flush()

        expect(observeRepublishBatch).toHaveBeenCalledWith('frontier', 1, 1, expect.any(Number))
        expect(observeRepublishBatch).toHaveBeenCalledWith('retry_1m', 1, 1, expect.any(Number))
        expect(observeRepublishFlush).toHaveBeenCalledWith(expect.any(Number))
    })

    it('splits one registrable domain at the job-count limit', async () => {
        const { batch, sent } = build()
        const candidates = Array.from({ length: MAX_JOBS_PER_RECORD + 1 }, (_, index) =>
            candidate({ originalRef: `imageurl:${index.toString().padStart(22, '0')}` })
        )

        await Promise.all(candidates.map((item) => batch.republish(item, item, 'pass_deadline')))
        await batch.flush()

        expect(sent).toHaveLength(2)
        expect(sent.map((item) => (parseJSON(item.value.toString()) as { jobs: unknown[] }).jobs.length)).toEqual([
            MAX_JOBS_PER_RECORD,
            1,
        ])
    })

    it('splits one registrable domain at the serialized-byte limit', async () => {
        const { batch, sent } = build()
        const longPath = 'a'.repeat(Math.floor(MAX_RECORD_BYTES / 2))
        const first = candidate({ currentUrl: `https://cdn.example.com/${longPath}/1.png` })
        const second = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: `https://cdn.example.com/${longPath}/2.png`,
        })

        await batch.republish(first, first, 'pass_deadline')
        await batch.republish(second, second, 'pass_deadline')
        await batch.flush()

        expect(sent).toHaveLength(2)
        expect(sent.every((item) => item.value.length <= MAX_RECORD_BYTES)).toBe(true)
    })

    it('refuses a delay longer than the largest deployed tier', async () => {
        const { batch, sent } = build()

        expect(await batch.republish(candidate(), candidate(), 'retry', 3_600_001)).toBe('refused_delay')
        await batch.flush()
        expect(sent).toEqual([])
    })

    it('refuses a redirect that has no hop left after republishing', async () => {
        const { batch, sent } = build()

        expect(await batch.republish(candidate({ remainingHops: 1 }), candidate(), 'redirect')).toBe('refused_delay')
        await batch.flush()
        expect(sent).toEqual([])
    })

    it('publishes every target-domain group from redirect fanout to the frontier', async () => {
        const { batch, sent } = build()
        const other = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://img.other.net/b.png',
            host: 'img.other.net',
            origin: 'https://img.other.net',
            registrableDomain: 'other.net',
        })

        await batch.republish(candidate(), candidate(), 'pass_deadline')
        await batch.republish(other, other, 'redirect')

        await expect(batch.flush()).resolves.toEqual({ failedUrls: 0 })
        expect(sent).toHaveLength(2)
        expect(sent.every((item) => item.topic === FRONTIER)).toBe(true)
        const redirected = sent.find((item) => item.key === 'other.net')!
        expect(parseCollectedUrlsRecord(redirected.value, 'other.net')).toMatchObject({
            ok: true,
            candidates: [{ lastRepublishReason: 'redirect', notBeforeMs: 0 }],
        })
    })

    it('bounds concurrent Kafka republish deliveries', async () => {
        let active = 0
        let peak = 0
        const releases: Array<() => void> = []
        const producer = {
            produce: () =>
                new Promise<void>((resolve) => {
                    active++
                    peak = Math.max(peak, active)
                    releases.push(() => {
                        active--
                        resolve()
                    })
                }),
        } as unknown as KafkaProducerWrapper
        const publisher = new FrontierPublisher(producer, {
            frontierTopic: FRONTIER,
            scrubTopic: SCRUB,
            delayTiers: TIERS,
            maxConcurrentImagePublishes: 2,
            maxConcurrentRepublishes: 2,
        })
        const batch = publisher.createRepublishBatch()

        for (const domain of ['one.example', 'two.example', 'three.example']) {
            const item = candidate({
                currentUrl: `https://${domain}/a.png`,
                host: domain,
                origin: `https://${domain}`,
                registrableDomain: domain,
            })
            await batch.republish(item, item, 'pass_deadline')
        }

        const flushing = batch.flush()
        expect(active).toBe(2)
        expect(peak).toBe(2)

        const firstTwo = releases.splice(0, 2)
        firstTwo[0]()
        for (let index = 0; index < 10; index++) {
            await Promise.resolve()
        }
        expect(active).toBe(2)
        expect(peak).toBe(2)

        firstTwo[1]()
        releases[0]()
        await expect(flushing).resolves.toEqual({ failedUrls: 0 })
    })

    it('reports every URL in a failed grouped message', async () => {
        const producer = { produce: () => Promise.reject(new Error('broker down')) } as unknown as KafkaProducerWrapper
        const publisher = new FrontierPublisher(producer, {
            frontierTopic: FRONTIER,
            scrubTopic: SCRUB,
            delayTiers: TIERS,
            maxConcurrentImagePublishes: 2,
            maxConcurrentRepublishes: 2,
        })
        const batch = publisher.createRepublishBatch()
        const failed = jest.spyOn(ImageFetchRequestMetrics, 'incRepublishFailed').mockImplementation()

        await batch.republish(candidate(), candidate(), 'pass_deadline')
        await batch.republish(candidate({ originalRef: `imageurl:${'b'.repeat(22)}` }), candidate(), 'pass_deadline')

        await expect(batch.flush()).resolves.toEqual({ failedUrls: 2 })
        expect(failed).toHaveBeenCalledTimes(2)
    })

    it('stops starting republish deliveries after the first failure', async () => {
        const produce = jest.fn(() => Promise.reject(new Error('broker down')))
        const producer = { produce } as unknown as KafkaProducerWrapper
        const publisher = new FrontierPublisher(producer, {
            frontierTopic: FRONTIER,
            scrubTopic: SCRUB,
            delayTiers: TIERS,
            maxConcurrentImagePublishes: 2,
            maxConcurrentRepublishes: 1,
        })
        const batch = publisher.createRepublishBatch()

        for (const domain of ['one.example', 'two.example', 'three.example']) {
            const item = candidate({
                currentUrl: `https://${domain}/a.png`,
                host: domain,
                origin: `https://${domain}`,
                registrableDomain: domain,
            })
            await batch.republish(item, item, 'pass_deadline')
        }

        await expect(batch.flush()).resolves.toEqual({ failedUrls: 3 })
        expect(produce).toHaveBeenCalledTimes(1)
    })

    it('does not start republish deliveries after the finalization deadline', async () => {
        const produce = jest.fn(() => Promise.resolve())
        const producer = { produce } as unknown as KafkaProducerWrapper
        const publisher = new FrontierPublisher(producer, {
            frontierTopic: FRONTIER,
            scrubTopic: SCRUB,
            delayTiers: TIERS,
            maxConcurrentImagePublishes: 2,
            maxConcurrentRepublishes: 2,
        })
        const batch = publisher.createRepublishBatch(performance.now())
        const deadlineExceeded = jest
            .spyOn(ImageFetchRequestMetrics, 'incRepublishFlushDeadlineExceeded')
            .mockImplementation()

        for (const domain of ['one.example', 'two.example', 'three.example']) {
            const item = candidate({
                currentUrl: `https://${domain}/a.png`,
                host: domain,
                origin: `https://${domain}`,
                registrableDomain: domain,
            })
            await batch.republish(item, item, 'pass_deadline')
        }

        await expect(batch.flush()).resolves.toEqual({ failedUrls: 3 })
        expect(produce).not.toHaveBeenCalled()
        expect(deadlineExceeded).toHaveBeenCalledTimes(1)
    })

    it('publishes fetched bytes under the original global ref', async () => {
        const { publisher, sent } = build()
        const fetchResult = {
            outcome: 'ok',
            redirects: 0,
            currentUrl: candidate().currentUrl,
            bytes: Buffer.from('image'),
            contentType: 'image/png',
            contentEncoding: 'gzip',
        } as ImageFetchResult

        await publisher.publishImage(candidate(), fetchResult)

        expect(sent[0]).toEqual({
            topic: SCRUB,
            key: `imageurl:${'a'.repeat(22)}`,
            value: Buffer.from('image'),
            headers: { 'content-type': 'image/png', 'content-encoding': 'gzip' },
        })
    })
})
