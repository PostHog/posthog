import { LRUCache } from 'lru-cache'

import { KeyStore, SessionKey } from '../types'

const MEMORY_CACHE_MAX_SIZE = 1_000_000
const MEMORY_CACHE_TTL_MS = 24 * 60 * 60 * 1000 // 24 hours

export class MemoryCachedKeyStore implements KeyStore {
    private readonly cache: LRUCache<string, SessionKey>

    constructor(
        private readonly delegate: KeyStore,
        options?: { maxSize?: number; ttlMs?: number }
    ) {
        this.cache = new LRUCache({
            max: options?.maxSize ?? MEMORY_CACHE_MAX_SIZE,
            ttl: options?.ttlMs ?? MEMORY_CACHE_TTL_MS,
        })
    }

    private cacheKey(sessionId: string, teamId: number): string {
        return `${teamId}:${sessionId}`
    }

    async start(): Promise<void> {
        await this.delegate.start()
    }

    async generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const key = await this.delegate.generateKey(sessionId, teamId)
        this.cache.set(this.cacheKey(sessionId, teamId), key)
        return key
    }

    async getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const cached = this.cache.get(this.cacheKey(sessionId, teamId))
        if (cached) {
            return cached
        }

        const key = await this.delegate.getKey(sessionId, teamId)
        this.cache.set(this.cacheKey(sessionId, teamId), key)
        return key
    }

    async deleteKey(sessionId: string, teamId: number): Promise<boolean> {
        // Clear cache first to ensure stale data isn't served
        this.cache.delete(this.cacheKey(sessionId, teamId))
        return this.delegate.deleteKey(sessionId, teamId)
    }

    stop(): void {
        this.delegate.stop()
    }
}
