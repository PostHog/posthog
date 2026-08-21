import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

const CRAWL_HISTORY_PREFIX = 'imgfetch:seen'

export function crawlHistoryKey(ref: string): string {
    const parsed = parseImageRef(ref)
    if (parsed?.source === 'url' && parsed.pseudoTeam) {
        return `${CRAWL_HISTORY_PREFIX}:${parsed.pseudoTeam}:${parsed.hash}`
    }
    return ref
}

export interface CrawlHistoryReadResult {
    known: Set<number>
    failed: Set<number>
}

export interface CrawlHistoryStore {
    read(keys: string[], nowMs: number): Promise<CrawlHistoryReadResult>
    record(keys: string[], nowMs: number, ttlSeconds: number): Promise<{ failed: Set<number> }>
}
