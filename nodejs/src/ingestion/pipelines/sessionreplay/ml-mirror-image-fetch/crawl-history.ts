const CRAWL_HISTORY_PREFIX = 'imgfetch:seen'

export function crawlHistoryKey(pseudoTeam: string, urlHash: string): string {
    return `${CRAWL_HISTORY_PREFIX}:${pseudoTeam}:${urlHash}`
}

export interface CrawlHistoryReadResult {
    known: Set<number>
    failed: Set<number>
}

export interface CrawlHistoryStore {
    read(keys: string[], nowMs: number): Promise<CrawlHistoryReadResult>
    record(keys: string[], nowMs: number, ttlSeconds: number): Promise<{ failed: Set<number> }>
}
