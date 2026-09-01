import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { PipelineResultType } from '~/ingestion/framework/results'
import type { CrawlHistoryStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/crawl-history'
import { MlImageFetchOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { RecordedTopHogMetric, createRecordingTopHog } from '~/tests/helpers/tophog'

import { CollectedUrl } from './parse-and-anonymize-step'
import { CollectedUrlsMessage, createProduceCollectedUrlsStep } from './produce-collected-urls-step'

describe('produceCollectedUrlsStep', () => {
    const PSEUDO_TEAM = 'a'.repeat(32)
    const CAPTURED_AT = 1_700_000_000_000
    let queued: { key: string; value: Buffer }[][]
    let outputs: IngestionOutputs<MlImageFetchOutput>
    let queueMessages: jest.Mock
    let topHog: TopHogRegistry
    let topHogRecords: Map<string, RecordedTopHogMetric[]>

    beforeEach(() => {
        queued = []
        queueMessages = jest.fn((_output: string, messages: { key: string; value: Buffer }[]) => {
            queued.push(messages)
            return Promise.resolve()
        })
        outputs = { queueMessages } as unknown as IngestionOutputs<MlImageFetchOutput>
        const recordingTopHog = createRecordingTopHog()
        topHog = recordingTopHog.registry
        topHogRecords = recordingTopHog.records
    })

    function collected(hash: string, host: string, url: string, domain = host): CollectedUrl {
        return { ref: `imageurl:${hash.padEnd(22, 'x')}`, pseudoTeam: PSEUDO_TEAM, url, host, domain }
    }

    function decode(batch: { key: string; value: Buffer }[]) {
        return batch.map((message) => ({
            key: message.key,
            value: parseJSON(message.value.toString()) as CollectedUrlsMessage,
        }))
    }

    function expectedJob(originalRef: string, currentUrl: string) {
        return {
            originalRef,
            currentUrl,
            remainingHops: 10,
            notBeforeMs: 0,
            firstSeenAtMs: CAPTURED_AT,
            fetchCount: 0,
            republishCount: 0,
            lastRepublishReason: null,
        }
    }

    async function run<T extends { collectedUrls?: CollectedUrl[]; message: { timestamp?: number } }>(
        step: ReturnType<typeof createProduceCollectedUrlsStep<T>>,
        input: T
    ) {
        const result = await step(input)
        if (result.type !== PipelineResultType.OK) {
            throw new Error(`expected ok, got ${result.type}`)
        }
        await Promise.all(result.sideEffects)
        return result
    }

    it('sends one message per operator, keyed by the domain, and strips the URLs from the element', async () => {
        // The clock is moved far from CAPTURED_AT on purpose: the record must carry the capture
        // time of the replay message, not the time the mirror produced it.
        jest.useFakeTimers().setSystemTime(new Date('2026-08-10T00:00:00.000Z'))
        try {
            const step = createProduceCollectedUrlsStep(outputs, topHog)
            const result = await run(step, {
                message: { timestamp: CAPTURED_AT },
                collectedUrls: [
                    collected('h1', 'cdn.example.com', 'https://cdn.example.com/a.jpg?sig=1'),
                    collected('h2', 'img.other.com', 'https://img.other.com/b.png'),
                    collected('h3', 'cdn.example.com', 'https://cdn.example.com/c.jpg'),
                ],
            })

            expect(result.value.collectedUrls).toBeUndefined()
            expect(queued).toHaveLength(1)
            expect(decode(queued[0])).toEqual([
                {
                    key: 'cdn.example.com',
                    value: {
                        v: 2,
                        jobs: [
                            expectedJob(`imageurl:h1xxxxxxxxxxxxxxxxxxxx`, 'https://cdn.example.com/a.jpg?sig=1'),
                            expectedJob(`imageurl:h3xxxxxxxxxxxxxxxxxxxx`, 'https://cdn.example.com/c.jpg'),
                        ],
                    },
                },
                {
                    key: 'img.other.com',
                    value: {
                        v: 2,
                        jobs: [expectedJob(`imageurl:h2xxxxxxxxxxxxxxxxxxxx`, 'https://img.other.com/b.png')],
                    },
                },
            ])
            expect(topHogRecords.get('ml_image_fetch_produced_urls_by_registrable_domain')).toEqual([
                { key: { registrable_domain: 'cdn.example.com' }, value: 2 },
                { key: { registrable_domain: 'img.other.com' }, value: 1 },
            ])
            expect(topHogRecords.get('ml_image_fetch_produced_urls_total')).toEqual([{ key: {}, value: 3 }])
        } finally {
            jest.useRealTimers()
        }
    })

    it('passes through elements with no collected URLs without producing', async () => {
        const step = createProduceCollectedUrlsStep(outputs, topHog)
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: undefined })
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [] })
        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('dedups an identical transport URL but produces a new URL for the same ref', async () => {
        const step = createProduceCollectedUrlsStep(outputs, topHog)
        const first = collected('h1', 'cdn.example.com', 'https://cdn.example.com/a.jpg?cb=old')
        const replacement = collected('h1', 'cdn.example.com', 'https://cdn.example.com/a.jpg?cb=new')
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [first] })
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [first, replacement] })
        expect(
            queued.map((batch) => decode(batch).map((message) => message.value.jobs.map((job) => job.currentUrl)))
        ).toEqual([[[first.url]], [[replacement.url]]])
    })

    it('produces an identical transport URL again after the dedup window', async () => {
        jest.useFakeTimers().setSystemTime(10_000)
        try {
            const step = createProduceCollectedUrlsStep(outputs, topHog, {
                producedRefCacheMax: 100,
                producedRefCacheWindowMs: 1_000,
            })
            const entry = collected('h1', 'cdn.example.com', 'https://cdn.example.com/a.jpg')

            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
            jest.setSystemTime(11_000)
            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })

            expect(queueMessages).toHaveBeenCalledTimes(2)
        } finally {
            jest.useRealTimers()
        }
    })

    it('swallows a failed produce and un-marks its refs so a later sighting produces again', async () => {
        queueMessages.mockRejectedValueOnce(new Error('broker down'))
        const step = createProduceCollectedUrlsStep(outputs, topHog)
        const entry = collected('h1', 'cdn.example.com', 'https://cdn.example.com/a.jpg')

        const result = await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
        expect(result.type).toBe(PipelineResultType.OK)
        expect(topHogRecords.get('ml_image_fetch_produced_urls_by_registrable_domain')).toBeUndefined()
        expect(topHogRecords.get('ml_image_fetch_produced_urls_total')).toBeUndefined()

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
        expect(queueMessages).toHaveBeenCalledTimes(2)
        // The second produce succeeded, so the ref dedups from then on.
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
        expect(queueMessages).toHaveBeenCalledTimes(2)
    })

    it('skips fresh crawl history and preserves expired or missing refs', async () => {
        const nowMs = 1_800_000_000_000
        jest.useFakeTimers().setSystemTime(nowMs)
        try {
            const fresh = collected('h1', 'img.example.com', 'https://img.example.com/fresh.png')
            const freshReplacement = collected('h1', 'img.example.com', 'https://img.example.com/fresh-v2.png')
            const expired = collected('h2', 'img.example.com', 'https://img.example.com/expired.png')
            const missing = collected('h3', 'img.example.com', 'https://img.example.com/missing.png')
            const read = jest.fn<
                ReturnType<Pick<CrawlHistoryStore, 'read'>['read']>,
                Parameters<Pick<CrawlHistoryStore, 'read'>['read']>
            >()
            read.mockResolvedValue(
                new Map([
                    [
                        fresh.ref,
                        {
                            kind: 'url' as const,
                            key: fresh.ref,
                            nextFetchAtMs: nowMs + 1,
                            storageExpiresAtMs: nowMs + 1,
                            outcome: 'ok',
                        },
                    ],
                    [
                        expired.ref,
                        {
                            kind: 'url' as const,
                            key: expired.ref,
                            nextFetchAtMs: nowMs,
                            storageExpiresAtMs: nowMs,
                            outcome: 'ok',
                        },
                    ],
                ])
            )
            const step = createProduceCollectedUrlsStep(outputs, topHog, { crawlHistory: { read } })

            await run(step, {
                message: { timestamp: CAPTURED_AT },
                collectedUrls: [fresh, freshReplacement, expired, missing],
            })

            expect(read).toHaveBeenCalledWith([fresh.ref, expired.ref, missing.ref])
            expect(decode(queued[0])[0].value.jobs.map((job) => job.originalRef)).toEqual([expired.ref, missing.ref])

            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [fresh] })
            expect(read).toHaveBeenCalledTimes(1)
        } finally {
            jest.useRealTimers()
        }
    })

    it('produces every URL when the crawl-history read fails', async () => {
        const entry = collected('h1', 'img.example.com', 'https://img.example.com/a.png')
        const read = jest.fn().mockRejectedValue(new Error('store unavailable'))
        const step = createProduceCollectedUrlsStep(outputs, topHog, { crawlHistory: { read } })

        const result = await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })

        expect(result.type).toBe(PipelineResultType.OK)
        expect(queueMessages).toHaveBeenCalledTimes(1)
        expect(decode(queued[0])[0].value.jobs.map((job) => job.originalRef)).toEqual([entry.ref])
    })

    test.each([
        ['inline image', `image:${PSEUDO_TEAM}:h1xxxxxxxxxxxxxxxxxxxx`],
        ['legacy team-scoped URL', `imageurl:${PSEUDO_TEAM}:h1xxxxxxxxxxxxxxxxxxxx`],
    ])('refuses to produce a %s ref', async (_name, ref) => {
        const step = createProduceCollectedUrlsStep(outputs, topHog, { producedRefCacheMax: 100 })

        await run(step, {
            message: { timestamp: CAPTURED_AT },
            collectedUrls: [
                {
                    ref,
                    pseudoTeam: PSEUDO_TEAM,
                    url: 'https://img.example.com/a.png',
                    host: 'img.example.com',
                    domain: 'example.com',
                },
            ],
        })

        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('drops a bytes ref that follows a usable one, and keeps the rest', async () => {
        // A guard that reads only the first entry passes this array and produces the bytes ref.
        const step = createProduceCollectedUrlsStep(outputs, topHog, { producedRefCacheMax: 100 })

        await run(step, {
            message: { timestamp: CAPTURED_AT },
            collectedUrls: [
                collected('h1', 'img.example.com', 'https://img.example.com/a.png'),
                {
                    ref: `image:${PSEUDO_TEAM}:h2xxxxxxxxxxxxxxxxxxxx`,
                    pseudoTeam: PSEUDO_TEAM,
                    url: 'https://img.example.com/inlined.png',
                    host: 'img.example.com',
                    domain: 'example.com',
                },
                collected('h3', 'img.example.com', 'https://img.example.com/c.png'),
            ],
        })

        const sent = decode(queued[0])
        expect(sent).toHaveLength(1)
        expect(sent[0].value.jobs.map((job) => job.originalRef)).toEqual([
            `imageurl:h1xxxxxxxxxxxxxxxxxxxx`,
            `imageurl:h3xxxxxxxxxxxxxxxxxxxx`,
        ])
    })

    it('packs many short urls into one record', async () => {
        // A fixed count would have cut this into several records and used a fraction of each. The
        // budget is bytes, so ordinary URLs pack until the bytes run out.
        const step = createProduceCollectedUrlsStep(outputs, topHog, { producedRefCacheMax: 100_000 })
        const many = Array.from({ length: 400 }, (_v, i) =>
            collected(`h${i}`.padEnd(22, 'x'), 'img.example.com', `https://img.example.com/${i}.png`)
        )

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: many })

        expect(decode(queued[0])).toHaveLength(1)
    })

    it('splits on the count bound even when the bytes would fit', async () => {
        // The fetcher refuses a record above its own count cap, whole. Byte packing alone would let
        // the collector's per-message cap in another crate decide how many entries a record holds.
        const step = createProduceCollectedUrlsStep(outputs, topHog, { producedRefCacheMax: 100_000 })
        const many = Array.from({ length: 1200 }, (_v, i) =>
            collected(`h${i}`.padEnd(22, 'x'), 'img.example.com', `https://img.example.com/${i}.png`)
        )

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: many })

        const sent = decode(queued[0])
        expect(sent.length).toBeGreaterThan(1)
        for (const record of sent) {
            expect(record.value.jobs.length).toBeLessThanOrEqual(1000)
        }
    })

    it('splits when the urls are long enough to fill a record', async () => {
        const step = createProduceCollectedUrlsStep(outputs, topHog, { producedRefCacheMax: 100_000 })
        const long = 'x'.repeat(2000)
        const many = Array.from({ length: 400 }, (_v, i) =>
            collected(`h${i}`.padEnd(22, 'x'), 'img.example.com', `https://img.example.com/${long}${i}.png`)
        )

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: many })

        expect(queued[0].length).toBeGreaterThan(1)
        const [first] = queued[0]
        expect(first.value.length).toBeGreaterThan(400 * 1024)
        for (const record of queued[0]) {
            expect(record.value.length).toBeLessThan(1_000_000)
        }
    })

    it('drops an entry whose ref names another team', async () => {
        const step = createProduceCollectedUrlsStep(outputs, topHog, { producedRefCacheMax: 100 })
        const otherTeam = 'b'.repeat(32)

        await run(step, {
            message: { timestamp: CAPTURED_AT },
            collectedUrls: [
                collected('h1', 'img.example.com', 'https://img.example.com/a.png'),
                {
                    ref: `imageurl:h2xxxxxxxxxxxxxxxxxxxx`,
                    pseudoTeam: otherTeam,
                    url: 'https://img.example.com/b.png',
                    host: 'img.example.com',
                    domain: 'img.example.com',
                },
            ],
        })

        const sent = decode(queued[0])
        expect(sent[0].value.jobs).toHaveLength(1)
        expect(sent[0].value.jobs[0].currentUrl).toBe('https://img.example.com/a.png')
    })

    it('puts a sharded CDN on one key, and keeps each host on its record', async () => {
        // A CDN that shards over numbered subdomains is one operator. Keying by host gave it one
        // budget per subdomain, which is the fragmentation this key exists to prevent. Each entry
        // still carries its own host, because robots.txt and the connection limit are per host.
        const step = createProduceCollectedUrlsStep(outputs, topHog, { producedRefCacheMax: 100 })

        await run(step, {
            message: { timestamp: CAPTURED_AT },
            collectedUrls: [
                collected('h1', 'img1.cdn.example.com', 'https://img1.cdn.example.com/a.png', 'example.com'),
                collected('h2', 'img8.cdn.example.com', 'https://img8.cdn.example.com/b.png', 'example.com'),
                collected('h3', 'assets.other.org', 'https://assets.other.org/c.png', 'other.org'),
            ],
        })

        const sent = decode(queued[0])
        expect(sent.map((m) => m.key).sort()).toEqual(['example.com', 'other.org'])
        const shared = sent.find((m) => m.key === 'example.com')!
        expect(shared.value.jobs.map((job) => job.currentUrl)).toEqual([
            'https://img1.cdn.example.com/a.png',
            'https://img8.cdn.example.com/b.png',
        ])
    })
})
