import { CollectedUrlBatch, RefDedupCache } from '@posthog/replay-anonymizer'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { PipelineResultType } from '~/ingestion/framework/results'
import type { CrawlHistoryStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/crawl-history'
import { CAPTURE_TIMESTAMP_HEADER } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'
import { MlImageFetchOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { RecordedTopHogMetric, createRecordingTopHog } from '~/tests/helpers/tophog'

import { CollectedUrlsMessage, FrontierJob, createProduceCollectedUrlsStep } from './produce-collected-urls-step'
import { ProducedTransportUrls } from './produced-refs'

interface UrlEntry {
    hash: string
    url: string
    domain: string
}

describe('produceCollectedUrlsStep', () => {
    const TEAM_ID = '42'
    const V3_NAMESPACE = `v3:${TEAM_ID}:2026-09`
    const CAPTURED_AT = 1_700_000_000_000
    let queued: { key: string; value: Buffer; headers?: Record<string, string> }[][]
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

    function createStep({
        producedRefCacheMax = 500_000,
        producedRefCacheWindowMs = 15 * 24 * 60 * 60 * 1000,
        crawlHistory,
    }: {
        producedRefCacheMax?: number
        producedRefCacheWindowMs?: number
        crawlHistory?: Pick<CrawlHistoryStore, 'read'>
    } = {}) {
        return createProduceCollectedUrlsStep(
            outputs,
            topHog,
            new ProducedTransportUrls(producedRefCacheMax, producedRefCacheWindowMs),
            { crawlHistory }
        )
    }

    function collected(hash: string, url: string, domain = new URL(url).host): UrlEntry {
        return { hash: hash.padEnd(22, 'x'), url, domain }
    }

    function ref(entry: UrlEntry, namespace: string | null = null): string {
        return namespace ? `imageurl:${namespace}:${entry.hash}` : `imageurl:${entry.hash}`
    }

    function urls(entries: UrlEntry[], namespace: string | null = null): CollectedUrlBatch {
        return CollectedUrlBatch.fromUrls(namespace, entries)!
    }

    function v3SessionInput(sessionId: string, entries: UrlEntry[], namespace = V3_NAMESPACE) {
        const key = {
            identity: { teamId: Number(TEAM_ID), sessionId, sessionMonth: '2026-09' },
            plaintext: Buffer.alloc(32),
            wrapped: Buffer.alloc(0),
        }
        return {
            message: { timestamp: CAPTURED_AT },
            headers: { session_id: sessionId },
            mlKeys: { session: key, image: key },
            collectedUrls: urls(entries, namespace),
        }
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

    async function run<T extends { collectedUrls?: CollectedUrlBatch; message: { timestamp?: number } }>(
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
            const step = createStep()
            const result = await run(step, {
                message: { timestamp: CAPTURED_AT },
                collectedUrls: urls([
                    collected('h1', 'https://cdn.example.com/a.jpg?sig=1'),
                    collected('h2', 'https://img.other.com/b.png'),
                    collected('h3', 'https://cdn.example.com/c.jpg'),
                ]),
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
            expect(queued[0].map((message) => message.headers?.[CAPTURE_TIMESTAMP_HEADER])).toEqual([
                String(CAPTURED_AT),
                String(CAPTURED_AT),
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
        const step = createStep()
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: undefined })
        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('dedups an identical transport URL but produces a new URL for the same ref', async () => {
        const step = createStep()
        const first = collected('h1', 'https://cdn.example.com/a.jpg?cb=old')
        const replacement = collected('h1', 'https://cdn.example.com/a.jpg?cb=new')
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([first]) })
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([first, replacement]) })
        expect(
            queued.map((batch) => decode(batch).map((message) => message.value.jobs.map((job) => job.currentUrl)))
        ).toEqual([[[first.url]], [[replacement.url]]])
    })

    it('dedups an identical transport URL that another session of the team collected', async () => {
        const step = createStep()
        const url = collected('h1', 'https://cdn.example.com/a.jpg')

        await run(step, v3SessionInput('01a0c669-8800-7000-8000-000000000001', [url]))
        await run(step, v3SessionInput('01a0c669-8800-7000-8000-000000000002', [url]))

        expect(queued).toHaveLength(1)
    })

    it('skips a v3 ref whose crawl history is fresh', async () => {
        const fresh = collected('h1', 'https://cdn.example.com/fresh.jpg')
        const missing = collected('h2', 'https://cdn.example.com/missing.jpg')
        const read = jest.fn<
            ReturnType<Pick<CrawlHistoryStore, 'read'>['read']>,
            Parameters<Pick<CrawlHistoryStore, 'read'>['read']>
        >()
        read.mockResolvedValue(
            new Map([
                [
                    ref(fresh, V3_NAMESPACE),
                    {
                        kind: 'url' as const,
                        key: ref(fresh, V3_NAMESPACE),
                        nextFetchAtMs: Number.MAX_SAFE_INTEGER,
                        storageExpiresAtMs: Number.MAX_SAFE_INTEGER,
                        outcome: 'ok',
                    },
                ],
            ])
        )
        const step = createStep({ crawlHistory: { read } })

        await run(step, v3SessionInput('01a0c669-8800-7000-8000-000000000001', [fresh, missing]))

        expect(decode(queued[0])[0].value.jobs.map((job) => job.originalRef)).toEqual([ref(missing, V3_NAMESPACE)])
    })

    it('produces an identical transport URL again after the dedup window', async () => {
        jest.useFakeTimers().setSystemTime(10_000)
        try {
            const step = createStep({
                producedRefCacheMax: 100,
                producedRefCacheWindowMs: 1_000,
            })
            const entry = collected('h1', 'https://cdn.example.com/a.jpg')

            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([entry]) })
            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([entry]) })
            jest.setSystemTime(11_000)
            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([entry]) })

            expect(queueMessages).toHaveBeenCalledTimes(2)
        } finally {
            jest.useRealTimers()
        }
    })

    it('swallows a failed produce and un-marks its refs so a later sighting produces again', async () => {
        queueMessages.mockRejectedValueOnce(new Error('broker down'))
        const step = createStep()
        const entry = collected('h1', 'https://cdn.example.com/a.jpg')

        const result = await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([entry]) })
        expect(result.type).toBe(PipelineResultType.OK)
        expect(topHogRecords.get('ml_image_fetch_produced_urls_by_registrable_domain')).toBeUndefined()
        expect(topHogRecords.get('ml_image_fetch_produced_urls_total')).toBeUndefined()

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([entry]) })
        expect(queueMessages).toHaveBeenCalledTimes(2)
        // The second produce succeeded, so the ref dedups from then on.
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([entry]) })
        expect(queueMessages).toHaveBeenCalledTimes(2)
    })

    it('skips fresh crawl history and preserves expired or missing refs', async () => {
        const nowMs = 1_800_000_000_000
        jest.useFakeTimers().setSystemTime(nowMs)
        try {
            const fresh = collected('h1', 'https://img.example.com/fresh.png')
            const freshReplacement = collected('h1', 'https://img.example.com/fresh-v2.png')
            const expired = collected('h2', 'https://img.example.com/expired.png')
            const missing = collected('h3', 'https://img.example.com/missing.png')
            const read = jest.fn<
                ReturnType<Pick<CrawlHistoryStore, 'read'>['read']>,
                Parameters<Pick<CrawlHistoryStore, 'read'>['read']>
            >()
            read.mockResolvedValue(
                new Map([
                    [
                        ref(fresh),
                        {
                            kind: 'url' as const,
                            key: ref(fresh),
                            nextFetchAtMs: nowMs + 1,
                            storageExpiresAtMs: nowMs + 1,
                            outcome: 'ok',
                        },
                    ],
                    [
                        ref(expired),
                        {
                            kind: 'url' as const,
                            key: ref(expired),
                            nextFetchAtMs: nowMs,
                            storageExpiresAtMs: nowMs,
                            outcome: 'ok',
                        },
                    ],
                ])
            )
            const step = createStep({ crawlHistory: { read } })

            await run(step, {
                message: { timestamp: CAPTURED_AT },
                collectedUrls: urls([fresh, freshReplacement, expired, missing]),
            })

            expect(read).toHaveBeenCalledWith([ref(fresh), ref(expired), ref(missing)])
            expect(decode(queued[0])[0].value.jobs.map((job) => job.originalRef)).toEqual([ref(expired), ref(missing)])

            await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([fresh]) })
            expect(read).toHaveBeenCalledTimes(1)
        } finally {
            jest.useRealTimers()
        }
    })

    it('produces every URL when the crawl-history read fails', async () => {
        const entry = collected('h1', 'https://img.example.com/a.png')
        const read = jest.fn().mockRejectedValue(new Error('store unavailable'))
        const step = createStep({ crawlHistory: { read } })

        const result = await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls([entry]) })

        expect(result.type).toBe(PipelineResultType.OK)
        expect(queueMessages).toHaveBeenCalledTimes(1)
        expect(decode(queued[0])[0].value.jobs.map((job) => job.originalRef)).toEqual([ref(entry)])
    })

    it('refuses to produce a legacy team-scoped URL ref', async () => {
        const step = createStep({ producedRefCacheMax: 100 })

        await run(step, {
            message: { timestamp: CAPTURED_AT },
            collectedUrls: urls([collected('h1', 'https://img.example.com/a.png')], 'a'.repeat(32)),
        })

        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('refuses to produce URLs whose refs name another team', async () => {
        const step = createStep({ producedRefCacheMax: 100 })
        const input = v3SessionInput(
            '01a0c669-8800-7000-8000-000000000001',
            [collected('h1', 'https://img.example.com/a.png')],
            'v3:43:2026-09'
        )

        await expect(step(input)).rejects.toThrow('ownership mismatch')
        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('packs many short urls into one record', async () => {
        // A fixed count would have cut this into several records and used a fraction of each. The
        // budget is bytes, so ordinary URLs pack until the bytes run out.
        const step = createStep({ producedRefCacheMax: 100_000 })
        const many = Array.from({ length: 400 }, (_v, i) =>
            collected(`h${i}`.padEnd(22, 'x'), `https://img.example.com/${i}.png`)
        )

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls(many) })

        expect(decode(queued[0])).toHaveLength(1)
    })

    it('splits on the count bound even when the bytes would fit', async () => {
        // The fetcher refuses a record above its own count cap, whole. Byte packing alone would let
        // the collector's per-message cap in another crate decide how many entries a record holds.
        const step = createStep({ producedRefCacheMax: 100_000 })
        const many = Array.from({ length: 1200 }, (_v, i) =>
            collected(`h${i}`.padEnd(22, 'x'), `https://img.example.com/${i}.png`)
        )

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls(many) })

        const sent = decode(queued[0])
        expect(sent.length).toBeGreaterThan(1)
        for (const record of sent) {
            expect(record.value.jobs.length).toBeLessThanOrEqual(1000)
        }
    })

    it('splits when the urls are long enough to fill a record', async () => {
        const step = createStep({ producedRefCacheMax: 100_000 })
        const long = 'x'.repeat(2000)
        const many = Array.from({ length: 400 }, (_v, i) =>
            collected(`h${i}`.padEnd(22, 'x'), `https://img.example.com/${long}${i}.png`)
        )

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: urls(many) })

        expect(queued[0].length).toBeGreaterThan(1)
        const [first] = queued[0]
        expect(first.value.length).toBeGreaterThan(400 * 1024)
        for (const record of queued[0]) {
            expect(record.value.length).toBeLessThan(1_000_000)
        }
    })

    it('puts a sharded CDN on one key, and keeps each host on its record', async () => {
        // A CDN that shards over numbered subdomains is one operator. Keying by host gave it one
        // budget per subdomain, which is the fragmentation this key exists to prevent. Each entry
        // still carries its own host, because robots.txt and the connection limit are per host.
        const step = createStep({ producedRefCacheMax: 100 })

        await run(step, {
            message: { timestamp: CAPTURED_AT },
            collectedUrls: urls([
                collected('h1', 'https://img1.cdn.example.com/a.png', 'example.com'),
                collected('h2', 'https://img8.cdn.example.com/b.png', 'example.com'),
                collected('h3', 'https://assets.other.org/c.png', 'other.org'),
            ]),
        })

        const sent = decode(queued[0])
        expect(sent.map((m) => m.key).sort()).toEqual(['example.com', 'other.org'])
        const shared = sent.find((m) => m.key === 'example.com')!
        expect(shared.value.jobs.map((job) => job.currentUrl)).toEqual([
            'https://img1.cdn.example.com/a.png',
            'https://img8.cdn.example.com/b.png',
        ])
    })

    describe('record bytes', () => {
        // The addon writes the records the fetcher parses. This TypeScript writer is the reference
        // for their bytes and split points, so a drift in escaping, key order or packing fails here.
        function jsonStringifyRecords(
            entries: UrlEntry[],
            namespace: string | null,
            sessionId: string | null,
            firstSeenAtMs: number,
            maxBytes: number,
            maxUrls: number
        ): { key: string; value: Buffer }[] {
            const byDomain = new Map<string, FrontierJob[]>()
            for (const entry of entries) {
                const job: FrontierJob = {
                    ...(sessionId ? { sessionId } : {}),
                    originalRef: namespace ? `imageurl:${namespace}:${entry.hash}` : `imageurl:${entry.hash}`,
                    currentUrl: entry.url,
                    remainingHops: 10,
                    notBeforeMs: 0,
                    firstSeenAtMs,
                    fetchCount: 0,
                    republishCount: 0,
                    lastRepublishReason: null,
                }
                const group = byDomain.get(entry.domain)
                if (group) {
                    group.push(job)
                } else {
                    byDomain.set(entry.domain, [job])
                }
            }
            return [...byDomain].flatMap(([domain, jobs]) =>
                packByBytes(jobs, maxBytes, maxUrls).map((slice) => ({
                    key: domain,
                    value: Buffer.from(JSON.stringify({ v: 2, jobs: slice } satisfies CollectedUrlsMessage)),
                }))
            )
        }

        function packByBytes(entries: FrontierJob[], maxBytes: number, maxUrls: number): FrontierJob[][] {
            const out: FrontierJob[][] = []
            let current: FrontierJob[] = []
            let bytes = Buffer.byteLength('{"v":2,"jobs":[]}')
            for (const entry of entries) {
                const size = Buffer.byteLength(JSON.stringify(entry)) + (current.length > 0 ? 1 : 0)
                if (current.length > 0 && (bytes + size > maxBytes || current.length >= maxUrls)) {
                    out.push(current)
                    current = []
                    bytes = Buffer.byteLength('{"v":2,"jobs":[]}')
                }
                current.push(entry)
                bytes += size
            }
            if (current.length > 0) {
                out.push(current)
            }
            return out
        }

        const entries: UrlEntry[] = [
            {
                hash: 'a'.repeat(22),
                url: 'https://cdn.example.com/a.png?q="quoted"&b=back\\slash',
                domain: 'example.com',
            },
            {
                hash: 'b'.repeat(22),
                url: 'https://cdn.example.com/\n\t\r\b\f\u0001\u001f\u007f',
                domain: 'example.com',
            },
            { hash: 'c'.repeat(22), url: 'https://bücher.example/é/中文/🎉', domain: 'bücher.example' },
            { hash: 'd'.repeat(22), url: 'https://cdn.example.com/  </script>', domain: 'example.com' },
            { hash: 'e'.repeat(22), url: `https://cdn.example.com/${'x'.repeat(300)}`, domain: 'example.com' },
            { hash: 'f'.repeat(22), url: 'https://bücher.example/second', domain: 'bücher.example' },
            { hash: 'g'.repeat(22), url: 'https://cdn.example.com/g', domain: 'example.com' },
        ]

        test.each([
            ['an unkeyed session', null, null],
            ['a keyed session', V3_NAMESPACE, '01a0c669-8800-7000-8000-000000000001'],
        ])('match JSON.stringify of the jobs at every budget for %s', (_name, namespace, sessionId) => {
            const firstSeenAtMs = 1_700_000_000_123
            const cache = new RefDedupCache(0)
            const differing: string[] = []
            let urlByteLengths: number[] = []
            for (const maxUrls of [2, 1000]) {
                for (let maxBytes = 1; maxBytes <= 2_500; maxBytes++) {
                    const batch = CollectedUrlBatch.fromUrls(namespace, entries)!
                    batch.claim(cache, 0)
                    const records = batch.buildRecords({
                        excludedRefs: [],
                        sessionId,
                        firstSeenAtMs,
                        maxRecordBytes: maxBytes,
                        maxRecordUrls: maxUrls,
                    })
                    const expected = jsonStringifyRecords(
                        entries,
                        namespace,
                        sessionId,
                        firstSeenAtMs,
                        maxBytes,
                        maxUrls
                    )
                    const identical =
                        expected.length === records.keys.length &&
                        expected.every(
                            (record, index) =>
                                record.key === records.keys[index] && record.value.equals(records.values[index])
                        )
                    if (!identical) {
                        differing.push(`maxRecordUrls=${maxUrls} maxRecordBytes=${maxBytes}`)
                    }
                    urlByteLengths = Array.from(records.urlByteLengths)
                }
            }
            expect(differing).toEqual([])
            expect(urlByteLengths).toEqual(entries.map(({ url }) => Buffer.byteLength(url)))
        })
    })
})
