import { Hub } from '../types'
import { LRUTokenRestrictionCache } from './db/token-restriction-cache'
import { logger } from './logger'

export enum RestrictionType {
    DROP_EVENT = 'drop_event',
    SKIP_PERSON = 'skip_person_processing',
    FORCE_OVERFLOW = 'force_overflow',
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
        const {
            cacheSize = 1000,
            ttlMs = 1000 * 60 * 60 * 24,
            dropEventTokens = [],
            skipPersonTokens = [],
            forceOverflowTokens = [],
        } = options

        this.hub = hub
        this.dropEventCache = new LRUTokenRestrictionCache({
            hitCacheSize: cacheSize,
            missCacheSize: cacheSize,
            ttlMs,
        })
        this.skipPersonCache = new LRUTokenRestrictionCache({
            hitCacheSize: cacheSize,
            missCacheSize: cacheSize,
            ttlMs,
        })
        this.forceOverflowCache = new LRUTokenRestrictionCache({
            hitCacheSize: cacheSize,
            missCacheSize: cacheSize,
            ttlMs,
        })
        this.staticDropEventList = new Set(dropEventTokens)
        this.staticSkipPersonList = new Set(skipPersonTokens)
        this.staticForceOverflowList = new Set(forceOverflowTokens)
    }

    async primeRestrictionsCache(token: string): Promise<void> {
        if (!token || !this.hub.USE_DYNAMIC_TOKEN_RESTRICTION_CONFIG) {
            return
        }

        // Check if we already have the values in cache
        const dropCached = this.dropEventCache.get(`${token}`)
        const skipCached = this.skipPersonCache.get(`${token}`)
        const overflowCached = this.forceOverflowCache.get(`${token}`)

        // If all values are already cached (hit or miss), return early
        if (dropCached !== undefined && skipCached !== undefined && overflowCached !== undefined) {
            return
        }

        // Make a single Redis call to fetch all three values
        try {
            const redisClient = await this.hub.redisPool.acquire()
            try {
                // Get all three values in a single pipeline
                const pipeline = redisClient.pipeline()
                pipeline.get(`${RestrictionType.DROP_EVENT}:${token}`)
                pipeline.get(`${RestrictionType.SKIP_PERSON}:${token}`)
                pipeline.get(`${RestrictionType.FORCE_OVERFLOW}:${token}`)
                const [dropResult, skipResult, overflowResult] = await pipeline.exec()

                // Store results in cache (null for misses)
                // TODO: What are these values? why is it an array? FIXME
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
