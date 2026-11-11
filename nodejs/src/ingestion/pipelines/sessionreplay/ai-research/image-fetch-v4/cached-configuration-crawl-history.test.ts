import { CachedConfigurationCrawlHistory } from './cached-configuration-crawl-history'
import {
    ConfigurationCacheItem,
    CrawlHistoryItem,
    CrawlHistoryStore,
    UrlCrawlHistoryItem,
    configurationCacheKey,
} from './crawl-history'

const NOW_MS = 1_700_000_000_000
const LIFETIME_MS = 60_000
const ROBOTS = configurationCacheKey('https://example.com', 'robots')
const URL_REF = 'imageurl:v4:7:2026-10:AAAAAAAAAAAAAAAAAAAAAA'

function robots(overrides: Partial<ConfigurationCacheItem> = {}): ConfigurationCacheItem {
    return {
        kind: 'robots',
        key: ROBOTS,
        origin: 'https://example.com',
        status: 'available',
        body: 'User-agent: *\nAllow: /',
        fetchedAtMs: NOW_MS,
        refreshAtMs: NOW_MS + 23 * 60 * 60 * 1000,
        freshUntilMs: NOW_MS + 24 * 60 * 60 * 1000,
        retryAtMs: NOW_MS,
        storageExpiresAtMs: NOW_MS + 30 * 24 * 60 * 60 * 1000,
        ...overrides,
    }
}

const urlHistory: UrlCrawlHistoryItem = {
    kind: 'url',
    key: URL_REF,
    nextFetchAtMs: NOW_MS + 60_000,
    storageExpiresAtMs: NOW_MS + 60_000,
    outcome: 'ok',
}

class RecordingStore implements CrawlHistoryStore {
    public readonly items = new Map<string, CrawlHistoryItem>()
    public readKeys: string[][] = []
    public writeError: Error | undefined
    /** A read answers with the rows it found when it started, once this resolves. */
    public readGate: Promise<void> = Promise.resolve()

    async read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        this.readKeys.push(keys)
        const found = new Map(
            keys.flatMap((key) => (this.items.has(key) ? [[key, this.items.get(key)!] as const] : []))
        )
        await this.readGate
        return found
    }

    write(items: CrawlHistoryItem[]): Promise<void> {
        for (const item of items) {
            this.items.set(item.key, item)
        }
        return this.writeError ? Promise.reject(this.writeError) : Promise.resolve()
    }
}

function build(...stored: CrawlHistoryItem[]): {
    history: CachedConfigurationCrawlHistory
    store: RecordingStore
    advance: (ms: number) => void
} {
    const store = new RecordingStore()
    for (const item of stored) {
        store.items.set(item.key, item)
    }
    let nowMs = NOW_MS
    const history = new CachedConfigurationCrawlHistory(store, { lifetimeMs: LIFETIME_MS, now: () => nowMs })
    return { history, store, advance: (ms) => (nowMs += ms) }
}

describe('CachedConfigurationCrawlHistory', () => {
    it.each([
        ['its lifetime ends', robots(), LIFETIME_MS],
        ['the item is due for a refresh', robots({ refreshAtMs: NOW_MS + 10_000 }), 10_000],
    ])('answers a configuration item from the process until %s', async (_name, item, heldForMs) => {
        const { history, store, advance } = build(item)

        expect((await history.read([ROBOTS])).get(ROBOTS)).toBe(item)
        advance(heldForMs - 1)
        expect((await history.read([ROBOTS])).get(ROBOTS)).toBe(item)
        expect(store.readKeys).toEqual([[ROBOTS]])

        advance(1)
        await history.read([ROBOTS])
        expect(store.readKeys).toEqual([[ROBOTS], [ROBOTS]])
    })

    it('asks the store on every read for URL history and for a configuration item with no row', async () => {
        const { history, store } = build(urlHistory)

        for (let read = 0; read < 2; read++) {
            expect([...(await history.read([URL_REF, ROBOTS]))]).toEqual([[URL_REF, urlHistory]])
        }
        expect(store.readKeys).toEqual([
            [URL_REF, ROBOTS],
            [URL_REF, ROBOTS],
        ])
    })

    it.each([
        ['after it read the row', false],
        ['while its read of the older row was in flight', true],
    ])('answers with the refusal this process wrote %s', async (_name, readInFlight) => {
        const { history, store } = build(robots())
        const refused = robots({ status: 'refused', body: undefined, fetchedAtMs: NOW_MS + 1 })
        let releaseRead: () => void = () => undefined
        if (readInFlight) {
            store.readGate = new Promise((resolve) => (releaseRead = resolve))
        }

        const olderRead = history.read([ROBOTS])
        if (!readInFlight) {
            await olderRead
        }
        await history.write([refused])
        releaseRead()
        await olderRead

        expect((await history.read([ROBOTS])).get(ROBOTS)).toBe(refused)
        expect(store.readKeys).toHaveLength(1)
    })

    it.each([
        ['after it read the row', false],
        ['while its read of the older row was in flight', true],
    ])(
        'asks the store again after a write that failed %s, because the row may hold the written item',
        async (_name, readInFlight) => {
            const { history, store } = build(robots())
            const refused = robots({ status: 'refused', body: undefined, fetchedAtMs: NOW_MS + 1 })
            let releaseRead: () => void = () => undefined
            if (readInFlight) {
                store.readGate = new Promise((resolve) => (releaseRead = resolve))
            }
            const olderRead = history.read([ROBOTS])
            if (!readInFlight) {
                await olderRead
            }
            store.writeError = new Error('the write timed out')

            await expect(history.write([refused])).rejects.toThrow('the write timed out')
            releaseRead()
            await olderRead

            expect((await history.read([ROBOTS])).get(ROBOTS)).toBe(refused)
        }
    )
})
