import { LRUCache } from 'lru-cache'

import { RedisPool } from '../types'
import { deserializeSessionKey, serializeSessionKey } from './session-key'
import { BaseKeyStore, SessionKey } from './types'

const CACHE_KEY_PREFIX = '@posthog/replay/recording-key'
const REDIS_CACHE_TTL_SECONDS = 60 * 60 * 24 // 24 hours
const MEMORY_CACHE_MAX_SIZE = 1_000_000
const MEMORY_CACHE_TTL_MS = 24 * 60 * 60 * 1000 // 24 hours

export class MemoryCachedKeyStore extends BaseKeyStore {
    private readonly cache: LRUCache<string, SessionKey>

    constructor(
        private readonly delegate: BaseKeyStore,
        options?: { maxSize?: number; ttlMs?: number }
    ) {
        super()
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
        const result = await this.delegate.deleteKey(sessionId, teamId)
        if (result) {
            const deletedKey = await this.delegate.getKey(sessionId, teamId)
            this.cache.set(this.cacheKey(sessionId, teamId), deletedKey)
        }
        return result
    }

    stop(): void {
        this.delegate.stop()
    }
}

export class RedisCachedKeyStore extends BaseKeyStore {
    constructor(
        private readonly delegate: BaseKeyStore,
        private readonly redisPool: RedisPool,
        private readonly ttlSeconds: number = REDIS_CACHE_TTL_SECONDS
    ) {
        super()
    }

    private cacheKey(sessionId: string, teamId: number): string {
        return `${CACHE_KEY_PREFIX}:${teamId}:${sessionId}`
    }

    async start(): Promise<void> {
        await this.delegate.start()
    }

    private async getCached(sessionId: string, teamId: number): Promise<SessionKey | null> {
        const client = await this.redisPool.acquire()
        try {
            const cached = await client.get(this.cacheKey(sessionId, teamId))
            return cached ? deserializeSessionKey(cached) : null
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async setCached(sessionId: string, teamId: number, key: SessionKey): Promise<void> {
        const client = await this.redisPool.acquire()
        try {
            await client.setex(this.cacheKey(sessionId, teamId), this.ttlSeconds, serializeSessionKey(key))
        } finally {
            await this.redisPool.release(client)
        }
    }

    async generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const key = await this.delegate.generateKey(sessionId, teamId)
        await this.setCached(sessionId, teamId, key)
        return key
    }

    async getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const cached = await this.getCached(sessionId, teamId)
        if (cached) {
            return cached
        }

        const key = await this.delegate.getKey(sessionId, teamId)
        await this.setCached(sessionId, teamId, key)
        return key
    }

    async deleteKey(sessionId: string, teamId: number): Promise<boolean> {
        const result = await this.delegate.deleteKey(sessionId, teamId)
        if (result) {
            const deletedKey = await this.delegate.getKey(sessionId, teamId)
            await this.setCached(sessionId, teamId, deletedKey)
        }
        return result
    }

    stop(): void {
        this.delegate.stop()
    }
}
