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

    /**
     * Returns the distinct ids not seen within the TTL, without marking them:
     * callers mark via touch only after their emission succeeds, so a failed
     * read or produce leaves the ids eligible for the retry to heal.
     */
    unseen(teamId: number, distinctIds: string[]): string[] {
        return distinctIds.filter((distinctId) => !this.cache.has(`${teamId}:${distinctId}`))
    }

    /** Marks handled mappings so a following no-op does not re-emit them. */
    touch(teamId: number, distinctIds: string[]): void {
        for (const distinctId of distinctIds) {
            this.cache.set(`${teamId}:${distinctId}`, true)
        }
    }
}
