export interface HttpCacheMetadata {
    requestTimeMs: number
    responseTimeMs: number
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
