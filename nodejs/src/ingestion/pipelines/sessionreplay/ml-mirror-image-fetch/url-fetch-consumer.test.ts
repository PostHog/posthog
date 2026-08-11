import { Message } from 'node-rdkafka'

import { UrlFetchConsumer } from './url-fetch-consumer'
import { LedgerEntry, UrlLedger, ledgerKey } from './url-ledger'

const TEAM = '0123456789abcdef0123456789abcdef'
const OTHER_TEAM = 'fedcba9876543210fedcba9876543210'
const NOW = 1_700_000_000_000

/** The ref format fixes the hash at 22 base64url characters, so a short test name has to be padded. */
const hash = (name: string): string => name.padEnd(22, '0')

function ref(name: string, team: string = TEAM): string {
    return `imageurl:${team}:${hash(name)}`
}

class FakeLedger {
    public readonly stored = new Map<string, LedgerEntry>()
    public readFailure: Error | null = null
    public writeFailure: Error | null = null
    public reads = 0

    getMany(keys: string[]): Promise<(LedgerEntry | null)[]> {
        this.reads++
        if (this.readFailure) {
            return Promise.reject(this.readFailure)
        }
        return Promise.resolve(keys.map((key) => this.stored.get(key) ?? null))
    }

    recordMany(entries: { key: string; entry: LedgerEntry }[]): Promise<void> {
        if (this.writeFailure) {
            return Promise.reject(this.writeFailure)
        }
        for (const { key, entry } of entries) {
            this.stored.set(key, entry)
        }
        return Promise.resolve()
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
    return {
        value: Buffer.from(JSON.stringify(body)),
        key: overrides.key === null ? null : Buffer.from(overrides.key ?? 'example.com'),
    } as unknown as Message
}

function url(name: string, host = 'cdn.example.com'): { ref: string; url: string; host: string } {
    return { ref: ref(name), url: `https://${host}/${name}.png`, host }
}

describe('UrlFetchConsumer', () => {
    let ledger: FakeLedger
    let consumer: UrlFetchConsumer

    const build = (dedupMaxRefs = 1000): UrlFetchConsumer =>
        new UrlFetchConsumer(ledger as unknown as UrlLedger, {
            maxAgeMs: 6 * 60 * 60 * 1000,
            dedupMaxRefs,
            dryRun: true,
        })

    beforeEach(() => {
        ledger = new FakeLedger()
        consumer = build()
    })

    const hashOf = (key: string): string => key.split(':')[2]

    it('writes one ledger entry per URL it would fetch', async () => {
        await consumer.handleBatch([record([url('a'), url('b')])], NOW)

        expect([...ledger.stored.keys()].map(hashOf).sort()).toEqual([hash('a'), hash('b')])
        expect(ledger.stored.get(ledgerKey(TEAM, hash('a')))?.outcome).toBe('seen')
    })

    it('does not re-record a URL another pod already reached', async () => {
        ledger.stored.set(ledgerKey(TEAM, hash('a')), { fetchedAtMs: NOW - 1000, outcome: 'seen' })

        await consumer.handleBatch([record([url('a'), url('b')])], NOW)

        // 'a' keeps the earlier entry rather than being counted and written again, which is what
        // makes the ledger measure the hit rate instead of the sighting rate.
        expect(ledger.stored.get(ledgerKey(TEAM, hash('a')))?.fetchedAtMs).toBe(NOW - 1000)
        expect(ledger.stored.get(ledgerKey(TEAM, hash('b')))?.fetchedAtMs).toBe(NOW)
    })

    it('collapses a repeated URL inside one batch into a single ledger write', async () => {
        await consumer.handleBatch([record([url('a')]), record([url('a')]), record([url('a')])], NOW)

        expect([...ledger.stored.keys()]).toEqual([ledgerKey(TEAM, hash('a'))])
    })

    it('does not consult the ledger for a URL this pod already handled', async () => {
        await consumer.handleBatch([record([url('a')])], NOW)
        const readsAfterFirst = ledger.reads

        await consumer.handleBatch([record([url('a')])], NOW)

        expect(ledger.reads).toBe(readsAfterFirst)
    })

    it('drops a URL older than the age limit without recording it', async () => {
        const sevenHoursAgo = NOW - 7 * 60 * 60 * 1000

        await consumer.handleBatch([record([url('a')], { capturedAtMs: sevenHoursAgo })], NOW)

        expect(ledger.stored.size).toBe(0)
    })

    it.each([
        ['an unsupported version', record([url('a')], { v: 2 })],
        ['a missing kafka key', record([url('a')], { key: null })],
        ['a body that is not json', { value: Buffer.from('{oh no'), key: Buffer.from('example.com') } as Message],
        ['an empty value', { value: null, key: Buffer.from('example.com') } as unknown as Message],
    ])('drops %s without throwing', async (_name, message) => {
        await expect(consumer.handleBatch([message], NOW)).resolves.toBeUndefined()

        expect(ledger.stored.size).toBe(0)
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

        expect([...ledger.stored.keys()].map(hashOf)).toEqual([hash('good')])
    })

    it('treats a URL as unseen when the ledger read fails, rather than stalling the partition', async () => {
        ledger.readFailure = new Error('redis down')

        await expect(consumer.handleBatch([record([url('a')])], NOW)).resolves.toBeUndefined()
    })

    it('survives a ledger write failure', async () => {
        ledger.writeFailure = new Error('redis down')

        await expect(consumer.handleBatch([record([url('a')])], NOW)).resolves.toBeUndefined()
    })
})
