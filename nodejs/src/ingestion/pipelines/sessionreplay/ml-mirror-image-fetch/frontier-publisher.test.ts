import { KafkaProducerWrapper } from '~/common/kafka/producer'

import { FetchCandidate, MAX_HOPS, parseCollectedUrlsRecord } from './collected-urls-record'
import { FrontierPublisher } from './frontier-publisher'
import { ImageFetchResult } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'

const FRONTIER = 'session_replay_image_fetch'
const SCRUB = 'session_replay_image_scrub'
const TIERS = [
    { topic: 'retry_1m', delayMs: 60_000 },
    { topic: 'retry_10m', delayMs: 600_000 },
    { topic: 'retry_1h', delayMs: 3_600_000 },
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

function build(): { publisher: FrontierPublisher; sent: SentMessage[] } {
    const sent: SentMessage[] = []
    const producer = {
        produce: (message: { topic: string; key: Buffer; value: Buffer; headers?: Record<string, string> }) => {
            sent.push({ ...message, key: message.key.toString() })
            return Promise.resolve()
        },
    } as unknown as KafkaProducerWrapper
    return {
        publisher: new FrontierPublisher(producer, {
            frontierTopic: FRONTIER,
            scrubTopic: SCRUB,
            delayTiers: TIERS,
            maxConcurrentImagePublishes: 2,
        }),
        sent,
    }
}

describe('FrontierPublisher', () => {
    beforeEach(() => jest.useFakeTimers().setSystemTime(1_700_000_000_000))
    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('keeps the global ref and durable state when it republishes a redirect', async () => {
        const { publisher, sent } = build()
        const republished = jest.spyOn(ImageFetchRequestMetrics, 'incRepublished').mockImplementation()
        const result = await publisher.republish(
            candidate(),
            {
                currentUrl: 'https://img.other.net/a.png',
                host: 'img.other.net',
                origin: 'https://img.other.net',
                registrableDomain: 'other.net',
            },
            'redirect'
        )

        expect(result).toBe('published')
        expect(republished).toHaveBeenCalledWith('redirect', 'frontier')
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
            ],
        })
    })

    it.each([
        ['an unspecified retry', 0, 'retry_1m', 60_000],
        ['a short retry', 30_000, 'retry_1m', 60_000],
        ['a medium retry', 120_000, 'retry_10m', 600_000],
        ['a long supported retry', 3_600_000, 'retry_1h', 3_600_000],
    ])('parks %s once in the smallest sufficient delay topic', async (_name, waitMs, topic, delayMs) => {
        const { publisher, sent } = build()
        const republished = jest.spyOn(ImageFetchRequestMetrics, 'incRepublished').mockImplementation()

        expect(await publisher.republish(candidate(), candidate(), 'retry', waitMs)).toBe('published')
        expect(republished).toHaveBeenCalledWith('retry', 'delay')
        expect(sent[0].topic).toBe(topic)
        expect(parseCollectedUrlsRecord(sent[0].value, 'example.com')).toMatchObject({
            ok: true,
            candidates: [{ notBeforeMs: 1_700_000_000_000 + delayMs }],
        })
    })

    it('refuses a delay longer than the largest deployed tier', async () => {
        const { publisher, sent } = build()

        expect(await publisher.republish(candidate(), candidate(), 'retry', 3_600_001)).toBe('refused_delay')
        expect(sent).toEqual([])
    })

    it('refuses a redirect that has no hop left after republishing', async () => {
        const { publisher, sent } = build()

        expect(await publisher.republish(candidate({ remainingHops: 1 }), candidate(), 'redirect')).toBe(
            'refused_delay'
        )
        expect(sent).toEqual([])
    })

    it('reports a failed produce without throwing', async () => {
        const producer = { produce: () => Promise.reject(new Error('broker down')) } as unknown as KafkaProducerWrapper
        const publisher = new FrontierPublisher(producer, {
            frontierTopic: FRONTIER,
            scrubTopic: SCRUB,
            delayTiers: TIERS,
            maxConcurrentImagePublishes: 2,
        })

        await expect(publisher.republish(candidate(), candidate(), 'retry')).resolves.toBe('failed')
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
