import { Redis } from 'ioredis'
import { DateTime } from 'luxon'

import { PluginsServerConfig } from '../types'
import { createRedis } from './utils'

export type RateLimitedResource = 'events' | 'recordings'

const CACHE_TTL_SECONDS = 60

export class RateLimiter {
    private serverConfig: PluginsServerConfig
    private redis: Redis | null
    private localCache: { [key: string]: string[] } = {}
    private localCacheExpiresAt: DateTime | null = null
    private localCacheRefreshingPromise: Promise<void> | null = null

    constructor(serverConfig: PluginsServerConfig) {
        this.serverConfig = serverConfig
        this.redis = null
    }

    public async refreshLocalCache(): Promise<{ [key: string]: string[] }> {
        if (!this.localCacheExpiresAt || this.localCacheExpiresAt < DateTime.utc()) {
            if (!this.localCacheRefreshingPromise) {
                // NOTE: We probably want a timeout here...
                // ALSO: We probably want to only await if the cache is empty, otherwise we can just return the cache and let the promise do its thing in the background
                this.localCacheRefreshingPromise = this.refreshCaches().then(() => {
                    this.localCacheExpiresAt = DateTime.utc().plus({ seconds: CACHE_TTL_SECONDS })
                    this.localCacheRefreshingPromise = null
                })
            }

            await this.localCacheRefreshingPromise
        }

        return this.localCache
    }

    private async refreshCaches(): Promise<void> {
        await this.connect()
        const [events, recordings] = await Promise.all([
            this.redis?.zrange(`@posthog-plugin-server/rate-limiter/events`, 0, -1),
            this.redis?.zrange(`@posthog-plugin-server/rate-limiter/recordings`, 0, -1),
        ])
        this.localCache = {
            events: events || [],
            recordings: recordings || [],
        }
    }

    public async checkLimited(resouce: RateLimitedResource, organization_id: string): Promise<boolean> {
        await this.refreshLocalCache()
        return this.localCache[resouce]?.includes(organization_id) || false
    }

    public async connect(): Promise<void> {
        // TODO: Ditch this in favour of the RedisPool (didn't look closely enough to see how it works...)
        if (!this.redis) {
            this.redis = await createRedis(this.serverConfig)
        }
    }

    public disconnect(): void {
        this.redis?.disconnect()
    }
}
