import { Message } from 'node-rdkafka'

import { UrlFetchConsumer } from './url-fetch-consumer'
import { SightingStore, sightingKey } from './url-sightings'

const TEAM = '0123456789abcdef0123456789abcdef'
const OTHER_TEAM = 'fedcba9876543210fedcba9876543210'
const NOW = 1_700_000_000_000

/** The ref format fixes the hash at 22 base64url characters, so a short test name has to be padded. */
const hash = (name: string): string => name.padEnd(22, '0')

function ref(name: string, team: string = TEAM): string {
    return `imageurl:${team}:${hash(name)}`
}

class FakeSightings implements SightingStore {
    public readonly stored = new Map<string, number>()
    public readFailure: Error | null = null
    public writeFailure: Error | null = null
    /** Keys whose individual write reports a per-command failure, as ioredis does inside a pipeline. */
    public partialWriteFailures = new Set<string>()
    public reads = 0

    read(keys: string[]): Promise<{ known: Set<number>; failed: number }> {
        this.reads++
        if (this.readFailure) {
            return Promise.reject(this.readFailure)
        }
        const known = new Set<number>()
        keys.forEach((key, index) => {
            if (this.stored.has(key)) {
                known.add(index)
            }
        })
        return Promise.resolve({ known, failed: 0 })
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

/** A real Message, so a field the consumer starts reading cannot be missing without the type saying so. */
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
    let sightings: FakeSightings
    let consumer: UrlFetchConsumer

    const build = (dedupMaxRefs = 1000): UrlFetchConsumer =>
        new UrlFetchConsumer(sightings, {
            maxAgeMs: 6 * 60 * 60 * 1000,
            dedupMaxRefs,
            dryRun: true,
        })

    beforeEach(() => {
        sightings = new FakeSightings()
        consumer = build()
    })

    const hashOf = (key: string): string => key.split(':').pop() as string

    it.each([NaN, 0, -1])('refuses to start with an age limit of %p', (maxAgeMs) => {
        // The knob arrives from env, where a typo parses to NaN. A NaN limit makes every comparison
        // false, so the lane silently stops shedding a backlog instead of failing.
        expect(() => new UrlFetchConsumer(sightings, { maxAgeMs, dedupMaxRefs: 10, dryRun: true })).toThrow(
            'SESSION_RECORDING_ML_IMAGE_FETCH_MAX_AGE_MS'
        )
    })

    it('writes one ledger entry per URL it would fetch', async () => {
        await consumer.handleBatch([record([url('a'), url('b')])], NOW)

        expect([...sightings.stored.keys()].map(hashOf).sort()).toEqual([hash('a'), hash('b')])
    })

    it('does not re-record a URL another pod already reached', async () => {
        sightings.stored.set(sightingKey(TEAM, hash('a')), NOW - 1000)

        await consumer.handleBatch([record([url('a'), url('b')])], NOW)

        // 'a' keeps the earlier entry rather than being counted and written again, which is what
        // makes the ledger measure the hit rate instead of the sighting rate.
        expect(sightings.stored.get(sightingKey(TEAM, hash('a')))).toBe(NOW - 1000)
        expect(sightings.stored.get(sightingKey(TEAM, hash('b')))).toBe(NOW)
    })

    it('collapses a repeated URL inside one batch into a single ledger write', async () => {
        await consumer.handleBatch([record([url('a')]), record([url('a')]), record([url('a')])], NOW)

        expect([...sightings.stored.keys()]).toEqual([sightingKey(TEAM, hash('a'))])
    })

    it('does not consult the store for a URL this pod already handled', async () => {
        await consumer.handleBatch([record([url('a')])], NOW)
        const readsAfterFirst = sightings.reads

        await consumer.handleBatch([record([url('a')])], NOW)

        expect(sightings.reads).toBe(readsAfterFirst)
    })

    it('drops a URL older than the age limit without recording it', async () => {
        const sevenHoursAgo = NOW - 7 * 60 * 60 * 1000

        await consumer.handleBatch([record([url('a')], { capturedAtMs: sevenHoursAgo })], NOW)

        expect(sightings.stored.size).toBe(0)
    })

    it.each([
        ['an unsupported version', record([url('a')], { v: 2 })],
        ['a missing kafka key', record([url('a')], { key: null })],
        ['a body that is not json', message(Buffer.from('{oh no'), 'example.com')],
        ['an empty value', message(null, 'example.com')],
    ])('drops %s without throwing', async (_name, message) => {
        await expect(consumer.handleBatch([message], NOW)).resolves.toBeUndefined()

        expect(sightings.stored.size).toBe(0)
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
    ])('rejects %s while keeping the rest of the record', async (_name, bad) => {
        await consumer.handleBatch([record([bad as ReturnType<typeof url>, url('good')])], NOW)

        expect([...sightings.stored.keys()].map(hashOf)).toEqual([hash('good')])
    })

    it('does not mark the pod cache for a URL whose write failed', async () => {
        sightings.partialWriteFailures.add(sightingKey(TEAM, hash('a')))

        await consumer.handleBatch([record([url('a')])], NOW)
        const readsAfterFirst = sightings.reads
        await consumer.handleBatch([record([url('a')])], NOW)

        // The URL is in no durable store, so the next sighting has to reach the store again rather
        // than be suppressed locally and vanish from the measurement.
        expect(sightings.reads).toBe(readsAfterFirst + 1)
    })

    it('rejects a host outside the domain the record is keyed by', async () => {
        // The key scopes the per-site budget, so a foreign host would spend another site's allowance.
        await consumer.handleBatch(
            [record([url('a', 'img.other-site.net'), url('good', 'cdn.example.com')], { key: 'example.com' })],
            NOW
        )

        expect([...sightings.stored.keys()].map(hashOf)).toEqual([hash('good')])
    })

    it('drops a record carrying more URLs than any producer sends', async () => {
        const many = Array.from({ length: 1100 }, (_value, index) => url(`u${index}`))

        await consumer.handleBatch([record(many)], NOW)

        expect(sightings.stored.size).toBe(0)
    })

    it('treats a URL as unseen when the store read fails, rather than stalling the partition', async () => {
        sightings.readFailure = new Error('redis down')

        await expect(consumer.handleBatch([record([url('a')])], NOW)).resolves.toBeUndefined()
    })

    it('survives a store write failure', async () => {
        sightings.writeFailure = new Error('redis down')

        await expect(consumer.handleBatch([record([url('a')])], NOW)).resolves.toBeUndefined()
    })
})
