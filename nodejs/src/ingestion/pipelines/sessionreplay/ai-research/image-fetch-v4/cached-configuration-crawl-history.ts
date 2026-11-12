import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import { ConfigurationCacheItem, CrawlHistoryItem, CrawlHistoryStore, isConfigurationCacheKey } from './crawl-history'

const DEFAULT_LIFETIME_MS = 2 * 60 * 1000
const DEFAULT_MAX_ENTRIES = 20_000
const DEFAULT_MAX_BYTES = 96 * 1024 * 1024
const ENTRY_OVERHEAD_BYTES = 512

const heldReads = new Counter({
    name: 'ai_research_v4_image_fetch_configuration_item_reads_total',
    help: 'Configuration items a v4 crawl-history read asked for, by whether this process held them or asked the store.',
    labelNames: ['source'],
})

export interface CachedConfigurationCrawlHistoryOptions {
    lifetimeMs?: number
    maxEntries?: number
    maxBytes?: number
    now?: () => number
}

interface HeldItem {
    item: ConfigurationCacheItem
    validUntilMs: number
}

/**
 * Holds the robots and TDMRep items this process read or wrote, so a batch asks the store only for the origins it does
 * not hold. An entry is the item the store returned, so the policy decides from it as from a read. Another pod can
 * replace the row, and this process sees that after `lifetimeMs` at the latest.
 */
export class CachedConfigurationCrawlHistory implements CrawlHistoryStore {
    private readonly held: LRUCache<string, HeldItem>
    /** The keys a write wrote while each read was in flight. What such a read returns for them can be the older row. */
    private readonly reads = new Set<Set<string>>()
    private readonly writing = new Map<string, number>()
    private readonly lifetimeMs: number
    private readonly now: () => number

    constructor(
        private readonly store: CrawlHistoryStore,
        options: CachedConfigurationCrawlHistoryOptions = {}
    ) {
        this.lifetimeMs = options.lifetimeMs ?? DEFAULT_LIFETIME_MS
        this.now = options.now ?? Date.now
        this.held = new LRUCache({
            max: options.maxEntries ?? DEFAULT_MAX_ENTRIES,
            maxSize: options.maxBytes ?? DEFAULT_MAX_BYTES,
            sizeCalculation: ({ item }) => 2 * (item.key.length + (item.body?.length ?? 0)) + ENTRY_OVERHEAD_BYTES,
        })
    }

    public async read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        const result = new Map<string, CrawlHistoryItem>()
        const asked: string[] = []
        const nowMs = this.now()
        let fromProcess = 0
        let fromStore = 0
        for (const key of keys) {
            if (!isConfigurationCacheKey(key)) {
                asked.push(key)
                continue
            }
            const item = this.heldItem(key, nowMs)
            if (item) {
                result.set(key, item)
                fromProcess += 1
            } else {
                asked.push(key)
                fromStore += 1
            }
        }
        heldReads.labels('process').inc(fromProcess)
        heldReads.labels('store').inc(fromStore)
        if (asked.length === 0) {
            return result
        }
        const written = new Set(asked.filter((key) => this.writing.has(key)))
        this.reads.add(written)
        const stored = await this.store.read(asked).finally(() => this.reads.delete(written))
        const readAtMs = this.now()
        for (const [key, item] of stored) {
            result.set(key, item)
            if (item.kind !== 'url' && !written.has(key)) {
                this.hold(item, readAtMs)
            }
        }
        return result
    }

    public async write(items: CrawlHistoryItem[]): Promise<void> {
        const configurationItems = items.filter((item): item is ConfigurationCacheItem => item.kind !== 'url')
        // A write that fails can still have reached the store, so the entry goes first and the next read asks the store.
        for (const { key } of configurationItems) {
            this.held.delete(key)
            this.writing.set(key, (this.writing.get(key) ?? 0) + 1)
            this.reads.forEach((written) => written.add(key))
        }
        try {
            await this.store.write(items)
        } finally {
            for (const { key } of configurationItems) {
                const left = this.writing.get(key)! - 1
                if (left > 0) {
                    this.writing.set(key, left)
                } else {
                    this.writing.delete(key)
                }
            }
        }
        const nowMs = this.now()
        for (const item of configurationItems) {
            this.hold(item, nowMs)
        }
    }

    private heldItem(key: string, nowMs: number): ConfigurationCacheItem | undefined {
        const held = this.held.get(key)
        if (!held) {
            return undefined
        }
        if (held.validUntilMs <= nowMs) {
            this.held.delete(key)
            return undefined
        }
        return held.item
    }

    private hold(item: ConfigurationCacheItem, nowMs: number): void {
        const validUntilMs = Math.min(item.refreshAtMs, nowMs + this.lifetimeMs)
        if (validUntilMs <= nowMs) {
            this.held.delete(item.key)
            return
        }
        this.held.set(item.key, { item, validUntilMs })
    }
}
