import { QUOTA_LIMITER_CACHE_KEY, QuotaResource } from '~/common/services/quota-limiting.service'
import { Hub, Team } from '~/types'

export async function setTeamQuotaLimited(
    hub: Hub,
    team: Pick<Team, 'api_token'>,
    resource: QuotaResource,
    limited: boolean
): Promise<void> {
    const redis = await hub.posthogRedisPool.acquire()
    try {
        if (limited) {
            await redis.zadd(QUOTA_LIMITER_CACHE_KEY + resource, Math.floor(Date.now() / 1000) + 3600, team.api_token)
        } else {
            await redis.zrem(QUOTA_LIMITER_CACHE_KEY + resource, team.api_token)
        }
    } finally {
        await hub.posthogRedisPool.release(redis)
    }
    hub.quotaLimiting.clearCache(resource)
}
