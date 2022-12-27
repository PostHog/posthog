import Redis from 'ioredis'

import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { RATE_LIMITER_CACHE_KEY, RateLimiter } from '../../src/utils/rate-limiter'
import { commonOrganizationId } from '../helpers/plugins'

describe('RateLimiter()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let redis: Redis.Redis
    let rateLimiter: RateLimiter

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        rateLimiter = hub.rateLimiter
        redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.db.redisPool.release(redis)
        jest.useFakeTimers({ advanceTimers: true })
    })

    afterEach(async () => {
        await closeHub()
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.clearAllMocks()
    })

    it('checks if an organization_id is rate limited', async () => {
        await redis.zadd(`${RATE_LIMITER_CACHE_KEY}events`, 1, commonOrganizationId)
        await redis.zadd(`${RATE_LIMITER_CACHE_KEY}recordings`, 1, commonOrganizationId)
        const isEventsRateLimited = await rateLimiter.checkLimited('events', commonOrganizationId)
        const isRecordingsRateLimited = await rateLimiter.checkLimited('recordings', commonOrganizationId)
        expect(isEventsRateLimited).toBe(true)
        expect(isRecordingsRateLimited).toBe(true)
    })

    it('checks that the rate limiter is caching the org ids', async () => {
        expect(await rateLimiter.checkLimited('events', commonOrganizationId)).toBe(false)
        // expect(await rateLimiter.checkLimited('recordings', commonOrganizationId)).toBe(false)

        await redis.zadd(`${RATE_LIMITER_CACHE_KEY}events`, 1, commonOrganizationId)
        await redis.zadd(`${RATE_LIMITER_CACHE_KEY}recordings`, 1, commonOrganizationId)

        // should be cached and still return false
        expect(await rateLimiter.checkLimited('events', commonOrganizationId)).toBe(false)
        expect(await rateLimiter.checkLimited('recordings', commonOrganizationId)).toBe(false)

        jest.advanceTimersByTime(60001)

        expect(await rateLimiter.checkLimited('events', commonOrganizationId)).toBe(true)
        expect(await rateLimiter.checkLimited('recordings', commonOrganizationId)).toBe(true)
    })
})
