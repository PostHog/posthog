import { logger, serializeError } from '~/common/utils/logger'
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

    // Best effort: the caller already has the key, so a failed write (e.g. READONLY after a failover) must not fail the request.
    // onlyIfAbsent keeps a lookup that read the key before a delete from overwriting the deletion marker written after it.
    private async setCached(
        sessionId: string,
        teamId: number,
        key: SessionKey,
        { onlyIfAbsent = false }: { onlyIfAbsent?: boolean } = {}
    ): Promise<void> {
        const startTime = performance.now()
        try {
            const client = await this.redisPool.acquire()
            try {
                const cacheKey = this.cacheKey(sessionId, teamId)
                if (onlyIfAbsent) {
                    await client.set(cacheKey, serializeSessionKey(key), 'EX', this.ttlSeconds, 'NX')
                } else {
                    await client.setex(cacheKey, this.ttlSeconds, serializeSessionKey(key))
                }
            } finally {
                await this.redisPool.release(client)
            }
        } catch (error) {
            SessionBatchMetrics.incrementKeystoreRedisWriteErrors()
            logger.warn('🔑', 'keystore_redis_cache_write_failed', { sessionId, teamId, error: serializeError(error) })
        } finally {
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

    async generateKey(sessionId: string, teamId: number, retentionDays: number): Promise<SessionKey> {
        const key = await this.delegate.generateKey(sessionId, teamId, retentionDays)
        await this.setCached(sessionId, teamId, key)
        return key
    }

    async getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const cached = await this.getCached(sessionId, teamId)
        if (cached) {
            return cached
        }

        const key = await this.delegate.getKey(sessionId, teamId)
        await this.setCached(sessionId, teamId, key, { onlyIfAbsent: true })
        return key
    }

    async deleteKey(sessionId: string, teamId: number, deletedBy: string): Promise<DeleteKeyResult> {
        // Clear cache first to ensure stale data isn't served
        await this.deleteCached(sessionId, teamId)
        const result = await this.delegate.deleteKey(sessionId, teamId, deletedBy)
        // The deletion has committed, so a cache error must not report it as failed: setCached only logs and counts it.
        await this.setCached(sessionId, teamId, {
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'deleted',
            deletedAt: result.deletedAt,
            deletedBy: result.deletedBy,
        })
        return result
    }

    stop(): void {
        this.delegate.stop()
    }
}
