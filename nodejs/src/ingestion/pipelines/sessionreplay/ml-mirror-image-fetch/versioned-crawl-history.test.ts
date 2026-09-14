import { CrawlHistoryItem, CrawlHistoryStore, configurationCacheKey } from './crawl-history'
import { VersionedCrawlHistory } from './versioned-crawl-history'

class MemoryHistory implements CrawlHistoryStore {
    readonly items = new Map<string, CrawlHistoryItem>()
    read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        return Promise.resolve(
            new Map(keys.flatMap((key) => (this.items.has(key) ? [[key, this.items.get(key)!] as const] : [])))
        )
    }
    write(items: CrawlHistoryItem[]): Promise<void> {
        for (const item of items) {
            this.items.set(item.key, item)
        }
        return Promise.resolve()
    }
}

describe('VersionedCrawlHistory', () => {
    it('isolates monthly image history while sharing robots and tdmrep by origin', async () => {
        const shared = new MemoryHistory()
        const images = new MemoryHistory()
        const history = new VersionedCrawlHistory(shared, images)
        const september = 'imageurl:v2:7:1:2026-09:aaaaaaaaaaaaaaaaaaaaaa'
        const october = september.replace('2026-09', '2026-10')
        const origin = 'https://example.com'
        const policies = (['robots', 'tdmrep'] as const).map((kind) => ({
            kind,
            key: configurationCacheKey(origin, kind),
            origin,
            status: 'available' as const,
            fetchedAtMs: 1,
            refreshAtMs: 100,
            freshUntilMs: 100,
            retryAtMs: 0,
            storageExpiresAtMs: 1000,
        }))
        await history.write([
            { kind: 'url', key: september, nextFetchAtMs: 100, storageExpiresAtMs: 1000, outcome: 'fetched' },
            ...policies,
        ])
        const result = await history.read([september, october, ...policies.map((item) => item.key)])
        expect(result.has(september)).toBe(true)
        expect(result.has(october)).toBe(false)
        expect([...shared.items.keys()]).toEqual(policies.map((item) => item.key))
        expect(policies.every((item) => result.get(item.key) === item)).toBe(true)
        expect([...images.items.keys()]).toEqual([september])
    })
})
