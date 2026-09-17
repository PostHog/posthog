import { CrawlHistoryItem, CrawlHistoryStore } from './crawl-history'

export class VersionedCrawlHistory implements CrawlHistoryStore {
    constructor(
        private readonly legacy: CrawlHistoryStore,
        private readonly v2: CrawlHistoryStore
    ) {}

    public async read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        const scoped = keys.filter((key) => key.startsWith('imageurl:v2:'))
        const legacy = keys.filter((key) => !key.startsWith('imageurl:v2:'))
        const results = await Promise.all([this.legacy.read(legacy), this.v2.read(scoped)])
        return new Map(results.flatMap((result) => [...result]))
    }

    public async write(items: CrawlHistoryItem[]): Promise<void> {
        await Promise.all([
            this.legacy.write(items.filter((item) => !item.key.startsWith('imageurl:v2:'))),
            this.v2.write(items.filter((item) => item.key.startsWith('imageurl:v2:'))),
        ])
    }
}
