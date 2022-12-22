import { DateTime } from 'luxon'

import { DB } from './db/db'

export type RateLimitedResource = 'events' | 'recordings'

const CACHE_TTL_SECONDS = 60

export class RateLimiter {
    private db: DB
    private localCache: { [key: string]: string[] } = {}
    private localCacheExpiresAt: DateTime | null = null
    private localCacheRefreshingPromise: Promise<void> | null = null

    constructor(db: DB) {
        this.db = db
    }

    public async refreshLocalCache(): Promise<{ [key: string]: string[] }> {
        if (!this.localCacheExpiresAt || DateTime.utc() > this.localCacheExpiresAt) {
            // If we are here, then we should refresh the cached values

            // We use a promise reference to ensure we don't do multiple refreshes at the same time
            if (!this.localCacheRefreshingPromise) {
                this.localCacheRefreshingPromise = this.refreshCaches().then(() => {
                    this.localCacheRefreshingPromise = null
                })
            }

            // If this is null then we have never loaded from redis so we should wait for the first load
            if (!this.localCacheExpiresAt) {
                await this.localCacheRefreshingPromise
            }
        }

        return this.localCache
    }

    private async refreshCaches(): Promise<void> {
        const [events, recordings] = await Promise.all([
            this.db.redisZRange(`@posthog-plugin-server/rate-limiter/events`, 0, -1),
            this.db.redisZRange(`@posthog-plugin-server/rate-limiter/recordings`, 0, -1),
        ])
        this.localCache = {
            events: events || [],
            recordings: recordings || [],
        }
        this.localCacheExpiresAt = DateTime.utc().plus({ seconds: CACHE_TTL_SECONDS })
    }

    public async checkLimited(resouce: RateLimitedResource, organization_id: string): Promise<boolean> {
        await this.refreshLocalCache()
        return this.localCache[resouce]?.includes(organization_id) || false
    }
}
