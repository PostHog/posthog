import { DateTime } from 'luxon'

import { DB } from './db/db'

export type RateLimitedResource = 'events' | 'recordings'

const CACHE_TTL_SECONDS = 60
export const RATE_LIMITER_CACHE_KEY = '@posthog-plugin-server/rate-limiter/'

export class RateLimiter {
    private db: DB
    public localCache: { [key: string]: string[] } = {}
    public localCacheExpiresAt: DateTime | null = null

    constructor(db: DB) {
        this.db = db
    }

    private async refreshCaches(): Promise<void> {
        if (!this.localCacheExpiresAt || DateTime.utc() > this.localCacheExpiresAt) {
            const [events, recordings] = await Promise.all([
                this.db.redisZRange(`${RATE_LIMITER_CACHE_KEY}events`, 0, -1),
                this.db.redisZRange(`${RATE_LIMITER_CACHE_KEY}recordings`, 0, -1),
            ])
            this.localCache = {
                events: events || [],
                recordings: recordings || [],
            }
            this.localCacheExpiresAt = DateTime.utc().plus({ seconds: CACHE_TTL_SECONDS })
        }
    }

    public async checkLimited(resource: RateLimitedResource, organization_id: string): Promise<boolean> {
        await this.refreshCaches()
        return this.localCache[resource]?.includes(organization_id) || false
    }
}
