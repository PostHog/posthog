import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, RedisPool, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { QUOTA_LIMITER_CACHE_KEY, QuotaLimiting, QuotaResource } from './quota-limiting.service'

describe('QuotaLimiting', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let service: QuotaLimiting
    let redisPool: RedisPool
    let team: Team
    let team2: Team

    const setupQuotaLimits = async (resource: QuotaResource, quotas: { token: string; limitedUntil: number }[]) => {
        const redis = await redisPool.acquire()
        await redis.del(QUOTA_LIMITER_CACHE_KEY + resource)
        for (const quota of quotas) {
            // NOTE: the python service stores this as seconds since epoch, so we need to convert to seconds
            await redis.zadd(QUOTA_LIMITER_CACHE_KEY + resource, Math.floor(quota.limitedUntil / 1000), quota.token)
        }
        await redisPool.release(redis)
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        service = new QuotaLimiting(hub, hub.teamManager)
        redisPool = service['redisPool']
        team = await getFirstTeam(hub)

        const otherTeamId = await createTeam(hub.db.postgres, team!.organization_id)
        team2 = (await getTeam(hub, otherTeamId))!

        await setupQuotaLimits('events', [])
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('should return false if no quota limits in place', async () => {
        expect(await service.isTeamQuotaLimited(team.id, 'events')).toBe(false)
    })

    it('should return true if quota limits in place', async () => {
        await setupQuotaLimits('events', [{ token: team.api_token, limitedUntil: Date.now() + 10000 }])
        expect(await service.isTeamQuotaLimited(team.id, 'events')).toBe(true)
        expect(await service.isTeamQuotaLimited(team2.id, 'events')).toBe(false)
    })

    it('should return false if quota limits in place but expired', async () => {
        await setupQuotaLimits('events', [{ token: team.api_token, limitedUntil: Date.now() - 10000 }])
        expect(await service.isTeamQuotaLimited(team.id, 'events')).toBe(false)
    })
})
