import { Redis } from 'ioredis'
import { DateTime } from 'luxon'

import { PluginsServerConfig } from '../types'
import { createRedis } from './utils'

export type RateLimitedResource = 'events' | 'recordings'

const CACHE_TTL_SECONDS = 60

export class RateLimiter {
    private serverConfig: PluginsServerConfig
    private redis: Redis | null
    private localCache: { [key: string]: number[] } = {}
    private localCacheExpiresAt: DateTime | null = null
    private localCacheRefreshingPromise: Promise<void> | null = null

    constructor(serverConfig: PluginsServerConfig) {
        this.serverConfig = serverConfig
        this.redis = null
    }

    public async refreshLocalCache(): Promise<{ [key: string]: number[] }> {
        if (!this.localCacheExpiresAt || this.localCacheExpiresAt < DateTime.utc()) {
            if (!this.localCacheRefreshingPromise) {
                // NOTE: We probably want a timeout here...
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
            events: events?.map((x) => parseInt(x)) || [],
            recordings: recordings?.map((x) => parseInt(x)) || [],
        }
    }

    public async checkLimited(resouce: RateLimitedResource, organization_id: number): Promise<boolean> {
        await this.refreshLocalCache()
        return this.localCache[resouce]?.includes(organization_id) || false
    }

    public async connect(): Promise<void> {
        if (!this.redis) {
            this.redis = await createRedis(this.serverConfig)
        }
    }

    public disconnect(): void {
        this.redis?.disconnect()
    }
}
