import { createRedisPool } from '~/utils/db/redis'
import { TeamManager } from '~/utils/team-manager'

import { PluginsServerConfig, RedisPool } from '../../types'
import { LazyLoader } from '../../utils/lazy-loader'
import { logger } from '../../utils/logger'

// subset of resources that we care about in this service
export type QuotaResource = 'events' | 'cdp_trigger_events'

export const QUOTA_LIMITER_CACHE_KEY = '@posthog/quota-limits/'

export interface QuotaLimitedToken {
    token: string
    limitedUntil: number
}

export interface QuotaLimitingResult {
    isLimited: boolean
    limitedUntil?: number
}

export class QuotaLimiting {
    private readonly redisPool: RedisPool
    private readonly limitedTokensLoader: LazyLoader<Record<string, number>>

    constructor(
        config: PluginsServerConfig,
        private readonly teamManager: TeamManager
    ) {
        this.redisPool = createRedisPool(config, 'posthog')

        this.limitedTokensLoader = new LazyLoader({
            name: 'quota_limited_tokens',
            loader: async (resources: string[]) => {
                return await this.loadLimitedTokensFromRedis(resources)
            },
            refreshAgeMs: 1000 * 60 * 60, // 1 hour cache here - we never need to hard refresh
            refreshBackgroundAgeMs: 1000 * 60, // 1 minute age is more than good enough
        })
    }

    public async isTeamQuotaLimited(teamId: number, resource: QuotaResource): Promise<boolean> {
        const team = await this.teamManager.getTeam(teamId)
        if (!team) {
            return false
        }
        return await this.isTeamTokenQuotaLimited(team.api_token, resource)
    }

    public async isTeamTokenQuotaLimited(teamToken: string, resource: QuotaResource): Promise<boolean> {
        const result = await this.getQuotaLimitedTokens(teamToken, resource)

        return result.isLimited
    }

    private async getQuotaLimitedTokens(teamToken: string, resource: QuotaResource): Promise<QuotaLimitingResult> {
        const now = Date.now()
        const limitedTokens = await this.limitedTokensLoader.get(resource)
        const limitedUntil = limitedTokens?.[teamToken]
        const isLimited = limitedUntil ? limitedUntil > now : false

        return {
            isLimited,
            limitedUntil: isLimited ? limitedUntil : undefined,
        }
    }

    /**
     * Clear the cache for a specific resource
     */
    public clearCache(resource: QuotaResource): void {
        this.limitedTokensLoader.markForRefresh(resource)
    }

    /**
     * Clear all caches
     */
    public clearAllCaches(): void {
        this.limitedTokensLoader.clear()
    }

    /**
     * Load limited tokens from Redis for the given resources
     */
    private async loadLimitedTokensFromRedis(resources: string[]): Promise<Record<string, Record<string, number>>> {
        const now = Date.now() / 1000 // Convert to seconds for Redis comparison
        const results: Record<string, Record<string, number>> = {}

        // NOTE: Load limited tokens for each resource from Redis
        for (const resource of resources) {
            try {
                const redis = await this.redisPool.acquire()
                try {
                    const cacheKey = `${QUOTA_LIMITER_CACHE_KEY}${resource}`

                    // Use ZRANGEBYSCORE to get tokens with scores (timestamps) greater than now
                    // This matches the Python implementation: zrangebyscore(key, min=now.timestamp(), max="+inf")
                    const limitedTokens = await redis.zrangebyscore(cacheKey, now, '+inf', 'WITHSCORES')

                    const resourceTokens: Record<string, number> = {}

                    // Process the results (token, score, token, score, ...)
                    for (let i = 0; i < limitedTokens.length; i += 2) {
                        const token = limitedTokens[i]
                        const score = limitedTokens[i + 1]

                        if (token && score) {
                            // Convert score back to milliseconds for consistency
                            resourceTokens[token] = Math.floor(parseFloat(score) * 1000)
                        }
                    }

                    results[resource] = resourceTokens

                    logger.debug('[QuotaLimiting] Loaded limited tokens', {
                        resource,
                        tokenCount: Object.keys(resourceTokens).length,
                    })
                } finally {
                    await this.redisPool.release(redis)
                }
            } catch (error) {
                logger.error('[QuotaLimiting] Error loading limited tokens from Redis', {
                    resource,
                    error: error instanceof Error ? error.message : String(error),
                })
                results[resource] = {}
            }
        }

        return results
    }
}
