import { Message } from 'node-rdkafka'

import { FetchCandidate } from './collected-urls-record'
import { CrawlHistoryReadResult, CrawlHistoryStore, crawlHistoryKey } from './crawl-history'
import { AttemptOutcome, FetchPass, isTerminal } from './fetch-runner'
import { FrontierPublisher } from './frontier-publisher'
import { UrlFetchConsumer } from './url-fetch-consumer'

const TEAM = '0123456789abcdef0123456789abcdef'
const OTHER_TEAM = 'fedcba9876543210fedcba9876543210'
const NOW = 1_700_000_000_000

/** The ref format fixes the hash at 22 base64url characters, so a short test name needs padding. */
const hash = (name: string): string => name.padEnd(22, '0')

function ref(name: string, team: string = TEAM): string {
    return `imageurl:${team}:${hash(name)}`
}

class FakeCrawlHistory implements CrawlHistoryStore {
    public readonly stored = new Map<string, number>()
    public readFailure: Error | null = null
    public writeFailure: Error | null = null
    /** Keys whose individual write reports a failure. */
    public partialWriteFailures = new Set<string>()
    /** Keys whose read did not complete, so the store can say nothing about them. */
    public partialReadFailures = new Set<string>()
    public reads = 0

    read(keys: string[], _nowMs: number): Promise<CrawlHistoryReadResult> {
        this.reads++
        if (this.readFailure) {
            return Promise.reject(this.readFailure)
        }
        const known = new Set<number>()
        const failed = new Set<number>()
        keys.forEach((key, index) => {
            if (this.partialReadFailures.has(key)) {
                failed.add(index)
            } else if (this.stored.has(key)) {
                known.add(index)
            }
        })
        return Promise.resolve({ known, failed })
    }

    record(keys: string[], nowMs: number): Promise<{ failed: Set<number> }> {
        if (this.writeFailure) {
            return Promise.reject(this.writeFailure)
        }
        const failed = new Set<number>()
        keys.forEach((key, index) => {
            if (this.partialWriteFailures.has(key)) {
                failed.add(index)
                return
            }
            this.stored.set(key, nowMs)
        })
        return Promise.resolve({ failed })
    }
}

/** A real Message, so the type fails if the consumer starts to read a field this omits. */
function message(value: Buffer | null, key: string | null): Message {
    return {
        value,
        key: key === null ? null : Buffer.from(key),
        size: value?.length ?? 0,
        topic: 'session_replay_image_fetch',
        partition: 0,
        offset: 0,
    }
}

function record(
    urls: { ref: string; url: string; host: string }[],
    overrides: { v?: unknown; pseudoTeam?: string; capturedAtMs?: number; key?: string | null } = {}
): Message {
    const body = {
        v: overrides.v ?? 1,
        pseudoTeam: overrides.pseudoTeam ?? TEAM,
        capturedAtMs: overrides.capturedAtMs ?? NOW,
        urls,
    }
    return message(Buffer.from(JSON.stringify(body)), overrides.key === null ? null : (overrides.key ?? 'example.com'))
}

function url(name: string, host = 'cdn.example.com'): { ref: string; url: string; host: string } {
    return { ref: ref(name), url: `https://${host}/${name}.png`, host }
}

describe('UrlFetchConsumer', () => {
    let crawlHistory: FakeCrawlHistory
    let consumer: UrlFetchConsumer
    let republished: { reason: string; waitMs: number }[]
    let publisher: FrontierPublisher

    const build = (dedupMaxRefs = 1000): UrlFetchConsumer =>
        new UrlFetchConsumer(crawlHistory, publisher, {
            maxAgeMs: 6 * 60 * 60 * 1000,
            dedupMaxRefs,
            seenTtlSeconds: 7 * 24 * 60 * 60,
            dryRun: true,
        })

    beforeEach(() => {
        crawlHistory = new FakeCrawlHistory()
        republished = []
        publisher = {
            republish: (_c: unknown, _t: unknown, reason: string, waitMs: number) => {
                republished.push({ reason, waitMs })
                return Promise.resolve(true)
            },
        } as unknown as FrontierPublisher
        consumer = build()
    })

    const hashOf = (key: string): string => key.split(':').pop() as string

    it.each([NaN, 0, -1])('refuses to start with an age limit of %p', (maxAgeMs) => {
        // The limit arrives from env, where a typo parses to NaN. A NaN limit makes every comparison
        // false, so the lane stops shedding a backlog rather than fails.
        expect(
            () =>
                new UrlFetchConsumer(crawlHistory, publisher, {
                    maxAgeMs,
                    dedupMaxRefs: 10,
                    seenTtlSeconds: 604_800,
                    dryRun: true,
                })
        ).toThrow('SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS')
    })

    it.each([NaN, 0, -1, 1.5, 7, 3599])('refuses to start with a seen TTL of %p', (seenTtlSeconds) => {
        // The TTL arrives from env, where a typo parses to NaN and a unit suffix truncates: "7d"
        // parses to 7, and a 7-second TTL empties the ledger as fast as it fills. A NaN expiry makes
        // every ledger write fail while the lane looks healthy.
        expect(
            () =>
                new UrlFetchConsumer(crawlHistory, publisher, {
                    maxAgeMs: 1000,
                    dedupMaxRefs: 10,
                    seenTtlSeconds,
                    dryRun: true,
                })
        ).toThrow('SESSION_RECORDING_ML_IMAGE_FETCH_SEEN_TTL_SECONDS')
    })

    it('writes one ledger entry per URL it would fetch', async () => {
        await consumer.handleBatch([record([url('a'), url('b')])], NOW)

        expect([...crawlHistory.stored.keys()].map(hashOf).sort()).toEqual([hash('a'), hash('b')])
    })

    it('does not re-record a URL another pod already reached', async () => {
        crawlHistory.stored.set(crawlHistoryKey(TEAM, hash('a')), NOW - 1000)

        await consumer.handleBatch([record([url('a'), url('b')])], NOW)

        // The earlier entry survives, so the store measures the hit rate rather than the rate of
        // first arrivals.
        expect(crawlHistory.stored.get(crawlHistoryKey(TEAM, hash('a')))).toBe(NOW - 1000)
        expect(crawlHistory.stored.get(crawlHistoryKey(TEAM, hash('b')))).toBe(NOW)
    })

    it('collapses a repeated URL inside one batch into a single ledger write', async () => {
        await consumer.handleBatch([record([url('a')]), record([url('a')]), record([url('a')])], NOW)

        expect([...crawlHistory.stored.keys()]).toEqual([crawlHistoryKey(TEAM, hash('a'))])
    })

    it('does not consult the store for a URL this pod already handled', async () => {
        await consumer.handleBatch([record([url('a')])], NOW)
        const readsAfterFirst = crawlHistory.reads

        await consumer.handleBatch([record([url('a')])], NOW)

        expect(crawlHistory.reads).toBe(readsAfterFirst)
    })

    it.each([
        ['still waiting out its delay', NOW + 60_000, 0, [{ reason: 'not_ready', waitMs: 60_000 }]],
        ['past its delay', NOW - 1, 1, []],
    ])(
        'handles a retry that is %s (requirement 15)',
        async (_name, notBeforeMs, expectedWrites, expectedRepublishes) => {
            // A record can come back before its wait is over, because a wait longer than the longest
            // delay topic goes round that topic again. An early fetch would reach a site that asked
            // to be left alone, and a crawl history entry would stop the trip the URL still makes.
            // It goes back for the rest of the wait, because nothing else holds it.
            const body = {
                v: 1,
                pseudoTeam: TEAM,
                capturedAtMs: NOW,
                notBeforeMs,
                urls: [url('a')],
            }
            const early = message(Buffer.from(JSON.stringify(body)), 'example.com')

            await consumer.handleBatch([early], NOW)

            expect(crawlHistory.stored.size).toBe(expectedWrites)
            expect(republished).toEqual(expectedRepublishes)
        }
    )

    it('records a URL that is not ready and has no hops left (requirements 12 and 24)', async () => {
        // It cannot go round again, and nothing else holds it. Without an entry it comes back on
        // every session that refers to the image and is dropped again each time.
        const body = {
            v: 1,
            pseudoTeam: TEAM,
            capturedAtMs: NOW,
            notBeforeMs: NOW + 60_000,
            hopsRemaining: 1,
            urls: [url('a')],
        }
        const spent = message(Buffer.from(JSON.stringify(body)), 'example.com')

        await consumer.handleBatch([spent], NOW)

        expect([...crawlHistory.stored.keys()].map(hashOf)).toEqual([hash('a')])
        expect(republished).toEqual([])
    })

    it('fails the batch when a URL that is not ready cannot be sent back (requirement 21)', async () => {
        publisher = { republish: () => Promise.resolve(false) } as unknown as FrontierPublisher
        const body = { v: 1, pseudoTeam: TEAM, capturedAtMs: NOW, notBeforeMs: NOW + 60_000, urls: [url('a')] }
        const early = message(Buffer.from(JSON.stringify(body)), 'example.com')

        await expect(build().handleBatch([early], NOW)).rejects.toThrow('account for 1')
        expect(crawlHistory.stored.size).toBe(0)
    })

    it('drops a URL older than the age limit without recording it', async () => {
        const sevenHoursAgo = NOW - 7 * 60 * 60 * 1000

        await consumer.handleBatch([record([url('a')], { capturedAtMs: sevenHoursAgo })], NOW)

        expect(crawlHistory.stored.size).toBe(0)
    })

    it.each([
        ['an unsupported version', record([url('a')], { v: 2 })],
        ['a missing kafka key', record([url('a')], { key: null })],
        ['a body that is not json', message(Buffer.from('{oh no'), 'example.com')],
        ['an empty value', message(null, 'example.com')],
    ])('drops %s without throwing', async (_name, message) => {
        await expect(consumer.handleBatch([message], NOW)).resolves.toBeUndefined()

        expect(crawlHistory.stored.size).toBe(0)
    })

    it.each([
        [
            'a ref belonging to another team',
            { ref: ref('a', OTHER_TEAM), url: 'https://cdn.example.com/a.png', host: 'cdn.example.com' },
        ],
        [
            'a bytes ref rather than a url ref',
            { ref: `image:${TEAM}:${hash('a')}`, url: 'https://cdn.example.com/a.png', host: 'cdn.example.com' },
        ],
        [
            'a url whose host contradicts the entry',
            { ref: ref('a'), url: 'https://evil.example.net/a.png', host: 'cdn.example.com' },
        ],
        ['a scheme we never fetch', { ref: ref('a'), url: 'ftp://cdn.example.com/a.png', host: 'cdn.example.com' }],
        [
            'a port the scheme does not own',
            { ref: ref('a'), url: 'https://cdn.example.com:11211/a.png', host: 'cdn.example.com' },
        ],
        [
            'a url carrying credentials',
            { ref: ref('a'), url: 'https://user:pw@cdn.example.com/a.png', host: 'cdn.example.com' },
        ],
    ])('rejects %s while keeping the rest of the record', async (_name, bad) => {
        await consumer.handleBatch([record([bad as ReturnType<typeof url>, url('good')])], NOW)

        expect([...crawlHistory.stored.keys()].map(hashOf)).toEqual([hash('good')])
    })

    it('does not mark the pod cache for a URL whose write failed', async () => {
        crawlHistory.partialWriteFailures.add(crawlHistoryKey(TEAM, hash('a')))

        await consumer.handleBatch([record([url('a')])], NOW)
        const readsAfterFirst = crawlHistory.reads
        await consumer.handleBatch([record([url('a')])], NOW)

        // No durable store holds the URL, so the next arrival must reach the store again rather than
        // stop in this pod and vanish from the measurement.
        expect(crawlHistory.reads).toBe(readsAfterFirst + 1)
    })

    it('rejects a host outside the domain the record is keyed by', async () => {
        // The key scopes the per-site budget, so a foreign host would spend another site's allowance.
        await consumer.handleBatch(
            [record([url('a', 'img.other-site.net'), url('good', 'cdn.example.com')], { key: 'example.com' })],
            NOW
        )

        expect([...crawlHistory.stored.keys()].map(hashOf)).toEqual([hash('good')])
    })

    it('drops a record carrying more URLs than any producer sends', async () => {
        const many = Array.from({ length: 1100 }, (_value, index) => url(`u${index}`))

        await consumer.handleBatch([record(many)], NOW)

        expect(crawlHistory.stored.size).toBe(0)
    })

    it('holds back a URL whose dedup read failed, rather than treating it as new', async () => {
        // To count it as new would fetch it. A store outage would then make every batch send the
        // full un-deduped volume at customer sites, because our own store is down.
        crawlHistory.partialReadFailures.add(crawlHistoryKey(TEAM, hash('a')))

        await expect(consumer.handleBatch([record([url('a'), url('b')])], NOW)).resolves.toBeUndefined()

        expect([...crawlHistory.stored.keys()].map(hashOf)).toEqual([hash('b')])
    })

    it('commits a batch the store could not answer for, rather than replaying it forever', async () => {
        // A store that answers nothing answers nothing for the next batch too, so a replay stops
        // the lane instead of saving the URL. Nothing is recorded, so the mirror offers it again.
        crawlHistory.readFailure = new Error('store down')

        await expect(consumer.handleBatch([record([url('a')])], NOW)).resolves.toBeUndefined()

        expect(crawlHistory.stored.size).toBe(0)
    })

    it('commits a batch whose store write failed, because the URL was fetched', async () => {
        // A missing crawl history entry costs one duplicate fetch later, which requirement 22
        // allows. A replay would cost the same duplicate and stall the partition too.
        crawlHistory.writeFailure = new Error('store down')

        await expect(consumer.handleBatch([record([url('a')])], NOW)).resolves.toBeUndefined()
    })

    it('replays the batch when the pass could not put a URL back, rather than committing past it', async () => {
        // Requirement 21. Nothing else holds a URL whose republish failed, so its offset must not
        // commit.
        const runner: FetchPass = {
            run: (candidates: FetchCandidate[]) =>
                Promise.resolve(
                    candidates.map((candidate) => ({
                        candidate,
                        outcome: 'timeout' as AttemptOutcome,
                        finished: false,
                        lost: true,
                    }))
                ),
        }
        const fetching = new UrlFetchConsumer(
            crawlHistory,
            publisher,
            { maxAgeMs: 6 * 60 * 60 * 1000, dedupMaxRefs: 1000, seenTtlSeconds: 604_800, dryRun: false },
            runner
        )

        await expect(fetching.handleBatch([record([url('lost')])], NOW)).rejects.toThrow('account for 1')
        // No crawl history entry, so the replay fetches the URL rather than skips it.
        expect(crawlHistory.stored.size).toBe(0)
    })

    it('refuses to leave dry run without a way to send the requests', () => {
        expect(
            () =>
                new UrlFetchConsumer(crawlHistory, publisher, {
                    maxAgeMs: 1000,
                    dedupMaxRefs: 10,
                    seenTtlSeconds: 604_800,
                    dryRun: false,
                })
        ).toThrow('fetch runner')
    })

    it('records only the URLs the fetch pass finished with', async () => {
        const outcomes: Record<string, AttemptOutcome> = {
            [hash('done')]: 'ok',
            [hash('gone')]: 'not_found',
            [hash('later')]: 'deadline',
            [hash('slow')]: 'timeout',
        }
        const runner: FetchPass = {
            run: (candidates: FetchCandidate[]) =>
                Promise.resolve(
                    candidates.map((candidate) => ({
                        candidate,
                        outcome: outcomes[candidate.urlHash],
                        finished: isTerminal(outcomes[candidate.urlHash]),
                        lost: false,
                    }))
                ),
        }
        const fetching = new UrlFetchConsumer(
            crawlHistory,
            publisher,
            { maxAgeMs: 6 * 60 * 60 * 1000, dedupMaxRefs: 1000, seenTtlSeconds: 604_800, dryRun: false },
            runner
        )

        await fetching.handleBatch([record([url('done'), url('gone'), url('later'), url('slow')])], NOW)

        // A crawl history entry stops this lane from ever reading a URL again, so an answered URL
        // gets one and a URL that only ran out of time does not.
        expect([...crawlHistory.stored.keys()].map(hashOf).sort()).toEqual([hash('done'), hash('gone')])
    })
})
