import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { PipelineResultType } from '~/ingestion/framework/results'
import { CollectedUrl } from '~/ingestion/pipelines/sessionreplay/parse-and-anonymize-step'
import { MlImageFetchOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { CollectedUrlsMessage, createProduceCollectedUrlsStep } from './produce-collected-urls-step'

describe('produceCollectedUrlsStep', () => {
    const PSEUDO_TEAM = 'a'.repeat(32)
    const CAPTURED_AT = 1_700_000_000_000
    let queued: { key: string; value: Buffer }[][]
    let outputs: IngestionOutputs<MlImageFetchOutput>
    let queueMessages: jest.Mock

    beforeEach(() => {
        queued = []
        queueMessages = jest.fn((_output: string, messages: { key: string; value: Buffer }[]) => {
            queued.push(messages)
            return Promise.resolve()
        })
        outputs = { queueMessages } as unknown as IngestionOutputs<MlImageFetchOutput>
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
            const step = createProduceCollectedUrlsStep(outputs)
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
        } finally {
            jest.useRealTimers()
        }
    })

    it('passes through elements with no collected URLs without producing', async () => {
        const step = createProduceCollectedUrlsStep(outputs)
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: undefined })
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [] })
        expect(queueMessages).not.toHaveBeenCalled()
    })

    it('dedups an identical transport URL but produces a new URL for the same ref', async () => {
        const step = createProduceCollectedUrlsStep(outputs)
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
            const step = createProduceCollectedUrlsStep(outputs, 100, 1_000)
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
        const step = createProduceCollectedUrlsStep(outputs)
        const entry = collected('h1', 'cdn.example.com', 'https://cdn.example.com/a.jpg')

        const result = await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
        expect(result.type).toBe(PipelineResultType.OK)

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
        expect(queueMessages).toHaveBeenCalledTimes(2)
        // The second produce succeeded, so the ref dedups from then on.
        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: [entry] })
        expect(queueMessages).toHaveBeenCalledTimes(2)
    })

    test.each([
        ['inline image', `image:${PSEUDO_TEAM}:h1xxxxxxxxxxxxxxxxxxxx`],
        ['legacy team-scoped URL', `imageurl:${PSEUDO_TEAM}:h1xxxxxxxxxxxxxxxxxxxx`],
    ])('refuses to produce a %s ref', async (_name, ref) => {
        const step = createProduceCollectedUrlsStep(outputs, 100)

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
        const step = createProduceCollectedUrlsStep(outputs, 100)

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
        const step = createProduceCollectedUrlsStep(outputs, 100_000)
        const many = Array.from({ length: 400 }, (_v, i) =>
            collected(`h${i}`.padEnd(22, 'x'), 'img.example.com', `https://img.example.com/${i}.png`)
        )

        await run(step, { message: { timestamp: CAPTURED_AT }, collectedUrls: many })

        expect(decode(queued[0])).toHaveLength(1)
    })

    it('splits on the count bound even when the bytes would fit', async () => {
        // The fetcher refuses a record above its own count cap, whole. Byte packing alone would let
        // the collector's per-message cap in another crate decide how many entries a record holds.
        const step = createProduceCollectedUrlsStep(outputs, 100_000)
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
        const step = createProduceCollectedUrlsStep(outputs, 100_000)
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
        const step = createProduceCollectedUrlsStep(outputs, 100)
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
        const step = createProduceCollectedUrlsStep(outputs, 100)

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
