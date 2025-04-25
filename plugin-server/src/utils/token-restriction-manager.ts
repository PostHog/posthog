import { Hub } from '../types'
import { LRUTokenRestrictionCache } from './db/token-restriction-cache'
import { logger } from './logger'

export enum RestrictionType {
    DROP_EVENT_FROM_INGESTION = 'drop_event_from_ingestion',
    SKIP_PERSON = 'skip_person',
    FORCE_OVERFLOW_FROM_INGESTION = 'force_overflow_from_ingestion',
}

export class TokenRestrictionManager {
    private dropEventCache: LRUTokenRestrictionCache
    private skipPersonCache: LRUTokenRestrictionCache
    private forceOverflowCache: LRUTokenRestrictionCache
    private hub: Hub
    private staticDropEventList: Set<string>
    private staticSkipPersonList: Set<string>
    private staticForceOverflowList: Set<string>

    constructor(
        hub: Hub,
        options: {
            cacheSize?: number
            ttlMs?: number
            dropEventTokens?: string[]
            skipPersonTokens?: string[]
            forceOverflowTokens?: string[]
        } = {}
    ) {
        const { dropEventTokens = [], skipPersonTokens = [], forceOverflowTokens = [] } = options

        this.hub = hub
        this.dropEventCache = new LRUTokenRestrictionCache({
            hitCacheSize: hub.TOKEN_RESTRICTION_CACHE_HIT_SIZE,
            missCacheSize: hub.TOKEN_RESTRICTION_CACHE_MISS_SIZE,
            ttlMs: hub.TOKEN_RESTRICTION_CACHE_TTL_MS,
        })
        this.skipPersonCache = new LRUTokenRestrictionCache({
            hitCacheSize: hub.TOKEN_RESTRICTION_CACHE_HIT_SIZE,
            missCacheSize: hub.TOKEN_RESTRICTION_CACHE_MISS_SIZE,
            ttlMs: hub.TOKEN_RESTRICTION_CACHE_TTL_MS,
        })
        this.forceOverflowCache = new LRUTokenRestrictionCache({
            hitCacheSize: hub.TOKEN_RESTRICTION_CACHE_HIT_SIZE,
            missCacheSize: hub.TOKEN_RESTRICTION_CACHE_MISS_SIZE,
            ttlMs: hub.TOKEN_RESTRICTION_CACHE_TTL_MS,
        })
        this.staticDropEventList = new Set(dropEventTokens)
        this.staticSkipPersonList = new Set(skipPersonTokens)
        this.staticForceOverflowList = new Set(forceOverflowTokens)
    }

    async primeRestrictionsCache(token: string): Promise<void> {
        if (!token || !this.hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG) {
            return
        }

        const dropCached = this.dropEventCache.get(`${token}`)
        const skipCached = this.skipPersonCache.get(`${token}`)
        const overflowCached = this.forceOverflowCache.get(`${token}`)

        if (dropCached !== undefined && skipCached !== undefined && overflowCached !== undefined) {
            return
        }

        try {
            const redisClient = await this.hub.redisPool.acquire()
            try {
                const pipeline = redisClient.pipeline()
                pipeline.get(`${RestrictionType.DROP_EVENT_FROM_INGESTION}:${token}`)
                pipeline.get(`${RestrictionType.SKIP_PERSON}:${token}`)
                pipeline.get(`${RestrictionType.FORCE_OVERFLOW_FROM_INGESTION}:${token}`)
                const [dropResult, skipResult, overflowResult] = await pipeline.exec()

                this.dropEventCache.set(`${token}`, (dropResult?.[1] as string) || null)
                this.skipPersonCache.set(`${token}`, (skipResult?.[1] as string) || null)
                this.forceOverflowCache.set(`${token}`, (overflowResult?.[1] as string) || null)
            } catch (error) {
                logger.warn('Error reading token restrictions from Redis', { error, token })
            } finally {
                await this.hub.redisPool.release(redisClient)
            }
        } catch (error) {
            logger.warn('Error acquiring Redis client from pool for token restrictions', { error })
        }
    }

    shouldDropEvent(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }

        const tokenDistinctIdKey = distinctId ? `${token}:${distinctId}` : undefined
        if (
            this.staticDropEventList.has(token) ||
            (tokenDistinctIdKey && this.staticDropEventList.has(tokenDistinctIdKey))
        ) {
            return true
        }

        if (!this.hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG) {
            return false
        }

        const cachedValue = this.dropEventCache.get(`${token}`)
        if (cachedValue === null) {
            return false
        }

        if (cachedValue) {
            const blockedIds = cachedValue.split(',')

            return (distinctId && blockedIds.includes(distinctId)) || blockedIds.includes(token)
        }

        return false
    }

    shouldSkipPerson(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }

        const tokenDistinctIdKey = distinctId ? `${token}:${distinctId}` : undefined
        if (
            this.staticSkipPersonList.has(token) ||
            (tokenDistinctIdKey && this.staticSkipPersonList.has(tokenDistinctIdKey))
        ) {
            return true
        }

        if (!this.hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG) {
            return false
        }

        const cachedValue = this.skipPersonCache.get(`${token}`)
        if (cachedValue === null) {
            return false
        }

        if (cachedValue) {
            const blockedIds = cachedValue.split(',')

            return (distinctId && blockedIds.includes(distinctId)) || blockedIds.includes(token)
        }

        return false
    }

    shouldForceOverflow(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }

        const tokenDistinctIdKey = distinctId ? `${token}:${distinctId}` : undefined
        if (
            this.staticForceOverflowList.has(token) ||
            (tokenDistinctIdKey && this.staticForceOverflowList.has(tokenDistinctIdKey))
        ) {
            return true
        }

        if (!this.hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG) {
            return false
        }

        const cachedValue = this.forceOverflowCache.get(`${token}`)
        if (cachedValue === null) {
            return false
        }

        if (cachedValue) {
            const blockedIds = cachedValue.split(',')
            return (distinctId && blockedIds.includes(distinctId)) || blockedIds.includes(token)
        }

        // NOTE we are returning false if we do not get a cache hit
        // cache should be primed for this token before we call this method
        return false
    }

    clear(): void {
        this.dropEventCache.clear()
        this.skipPersonCache.clear()
        this.forceOverflowCache.clear()
    }
}
