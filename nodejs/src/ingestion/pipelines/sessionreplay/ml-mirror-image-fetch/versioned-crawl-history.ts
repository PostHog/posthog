import { CrawlHistoryItem, CrawlHistoryStore } from './crawl-history'

/** A v2 or v3 reference carries its dataset version, so the two never share a frontier entry. */
const SCOPED_URL_REF = /^imageurl:v[23]:/

export class VersionedCrawlHistory implements CrawlHistoryStore {
    constructor(
        private readonly legacy: CrawlHistoryStore,
        private readonly v2: CrawlHistoryStore
    ) {}

    public async read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        const scoped = keys.filter((key) => SCOPED_URL_REF.test(key))
        const legacy = keys.filter((key) => !SCOPED_URL_REF.test(key))
        const results = await Promise.all([this.legacy.read(legacy), this.v2.read(scoped)])
        return new Map(results.flatMap((result) => [...result]))
    }

    public async write(items: CrawlHistoryItem[]): Promise<void> {
        await Promise.all([
            this.legacy.write(items.filter((item) => !SCOPED_URL_REF.test(item.key))),
            this.v2.write(items.filter((item) => SCOPED_URL_REF.test(item.key))),
        ])
    }
}
