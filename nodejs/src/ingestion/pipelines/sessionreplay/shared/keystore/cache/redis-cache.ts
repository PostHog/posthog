import { SessionBatchMetrics } from '~/ingestion/pipelines/sessionreplay/sessions/metrics'
import {
    deserializeSessionKey,
    serializeSessionKey,
} from '~/ingestion/pipelines/sessionreplay/shared/crypto/session-key'
import { DeleteKeyResult, KeyStore, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { RedisPool } from '~/types'

const CACHE_KEY_PREFIX = '@posthog/replay/recording-key'
const REDIS_CACHE_TTL_SECONDS = 60 * 60 * 24 // 24 hours

export class RedisCachedKeyStore implements KeyStore {
    constructor(
        private readonly delegate: KeyStore,
        private readonly redisPool: RedisPool,
        private readonly ttlSeconds: number = REDIS_CACHE_TTL_SECONDS
    ) {}

    private cacheKey(sessionId: string, teamId: number): string {
        return `${CACHE_KEY_PREFIX}:${teamId}:${sessionId}`
    }

    async start(): Promise<void> {
        await this.delegate.start()
    }

    private async getCached(sessionId: string, teamId: number): Promise<SessionKey | null> {
        const startTime = performance.now()
        const client = await this.redisPool.acquire()
        try {
            const cached = await client.get(this.cacheKey(sessionId, teamId))
            return cached ? deserializeSessionKey(cached) : null
        } finally {
            await this.redisPool.release(client)
            SessionBatchMetrics.observeKeystoreRedisLatency((performance.now() - startTime) / 1000)
        }
    }

    private async setCached(sessionId: string, teamId: number, key: SessionKey): Promise<void> {
        const startTime = performance.now()
        const client = await this.redisPool.acquire()
        try {
            await client.setex(this.cacheKey(sessionId, teamId), this.ttlSeconds, serializeSessionKey(key))
        } finally {
            await this.redisPool.release(client)
            SessionBatchMetrics.observeKeystoreRedisLatency((performance.now() - startTime) / 1000)
        }
    }

    private async deleteCached(sessionId: string, teamId: number): Promise<void> {
        const startTime = performance.now()
        const client = await this.redisPool.acquire()
        try {
            await client.del(this.cacheKey(sessionId, teamId))
        } finally {
            await this.redisPool.release(client)
            SessionBatchMetrics.observeKeystoreRedisLatency((performance.now() - startTime) / 1000)
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

    async deleteKey(sessionId: string, teamId: number, deletedBy: string): Promise<DeleteKeyResult> {
        // Clear cache first to ensure stale data isn't served
        await this.deleteCached(sessionId, teamId)
        return this.delegate.deleteKey(sessionId, teamId, deletedBy)
    }

    stop(): void {
        this.delegate.stop()
    }
}
