import { LRUCache } from 'lru-cache'

/**
 * Debounces re-emission of already-satisfied merge mappings. The cache is
 * process-local on purpose: a healing emission is only needed when an event
 * replays after a crash, and the crash restart empties the cache, so replays
 * always emit while steady-state duplicate merges stay suppressed.
 */
export class MergeMappingDebounce {
    private readonly cache: LRUCache<string, true>

    constructor(maxEntries: number, ttlMs: number) {
        this.cache = new LRUCache({ max: maxEntries, ttl: ttlMs })
    }

    /** Returns the distinct ids not seen within the TTL, marking them seen. */
    claim(teamId: number, distinctIds: string[]): string[] {
        return distinctIds.filter((distinctId) => {
            const key = `${teamId}:${distinctId}`
            if (this.cache.has(key)) {
                return false
            }
            this.cache.set(key, true)
            return true
        })
    }

    /** Marks freshly written mappings so an immediately following no-op does not re-emit them. */
    touch(teamId: number, distinctIds: string[]): void {
        for (const distinctId of distinctIds) {
            this.cache.set(`${teamId}:${distinctId}`, true)
        }
    }
}
