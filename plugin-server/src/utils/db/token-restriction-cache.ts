import LRU from 'lru-cache'
import { Counter } from 'prom-client'

export interface TokenRestrictionCache {
    get(key: string): string | null | undefined
    set(key: string, value: string | null): void
    clear(): void
}

const tokenRestrictionCacheRequests = new Counter({
    name: 'token_restriction_cache_requests_total',
    help: 'Total number of token restriction cache requests',
    labelNames: ['cache_type', 'result'] as const,
})

export class LRUTokenRestrictionCache implements TokenRestrictionCache{
    private hitCache: LRU<string, string>
    private missCache: LRU<string, boolean>

    constructor(options: {hitCacheSize?: number; missCacheSize?: number; ttlMs?: number }) {
        // NICKS TODO review these
        const { hitCacheSize = 1000, missCacheSize = 1000, ttlMs = 1000 * 60 * 60 * 24 } = options

        this.hitCache = new LRU<string, string>({
            max: hitCacheSize,
            maxAge: ttlMs,
        })

        this.missCache = new LRU<string, boolean>({
            max: missCacheSize,
            maxAge: ttlMs,
        })
    }

    get(key: string): string | null | undefined {
        const cachedValue = this.hitCache.get(key)
        if (cachedValue !== undefined) {
            tokenRestrictionCacheRequests.inc({cache_type: 'token-restriction-cache', result: 'hit'})
            return cachedValue
        }

        if (this.missCache.has(key)) {
            tokenRestrictionCacheRequests.inc({cache_type: 'token-restriction-cache', result: 'hit'})
            return null
        }

        tokenRestrictionCacheRequests.inc({cache_type: 'token-restriction-cache', result: 'miss'})
        return undefined
    }

    set(key: string, value: string | null): void {
        if (value === null) {
            this.missCache.set(key, true)
        } else {
            this.hitCache.set(key, value)
        }
    }

    clear(): void {
        this.hitCache.reset()
        this.missCache.reset()
    }
}