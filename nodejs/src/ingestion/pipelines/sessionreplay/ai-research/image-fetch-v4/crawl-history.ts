export interface HttpCacheMetadata {
    requestTimeMs: number
    responseTimeMs: number
    /**
     * A keyed hash of the URL that sent these headers, never the URL itself. Its validators are sent to that URL only.
     */
    responseUrlHmac?: string
    etag?: string
    lastModified?: string
    date?: string
    age?: string
    cacheControl?: string
    expires?: string
}

export interface UrlCrawlHistoryItem {
    kind: 'url'
    key: string
    nextFetchAtMs: number
    storageExpiresAtMs: number
    outcome: string
    cache?: HttpCacheMetadata
    /** When the lane last stored or refreshed the image of this reference. */
    storedAtMs?: number
}

export type ConfigurationFile = 'robots' | 'tdmrep'
export type ConfigurationStatus = 'available' | 'absent' | 'refused' | 'unreachable'

export interface ConfigurationCacheItem {
    kind: ConfigurationFile
    key: string
    origin: string
    status: ConfigurationStatus
    body?: string
    fetchedAtMs: number
    refreshAtMs: number
    freshUntilMs: number
    retryAtMs: number
    storageExpiresAtMs: number
}

export type CrawlHistoryItem = UrlCrawlHistoryItem | ConfigurationCacheItem

export function configurationCacheKey(origin: string, file: ConfigurationFile): string {
    return `imgfetch:config:${file}:${origin}`
}

export interface CrawlHistoryStore {
    read(keys: string[]): Promise<Map<string, CrawlHistoryItem>>
    write(items: CrawlHistoryItem[]): Promise<void>
}
