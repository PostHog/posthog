import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { RATE_LIMITER_CACHE_KEY, RateLimiter } from '../../src/utils/rate-limiter'
import { commonOrganizationId } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

describe('RateLimiter()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let rateLimiter: RateLimiter

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        rateLimiter = hub.rateLimiter
        jest.useFakeTimers({ advanceTimers: true })
    })

    afterEach(async () => {
        jest.clearAllTimers()
        jest.useRealTimers()
        await closeHub?.()
    })

    it('checks if an organization_id is rate limited', async () => {
        const redisClient = await hub.db.redisPool.acquire()
        await redisClient.zadd(`${RATE_LIMITER_CACHE_KEY}events`, 1, commonOrganizationId)
        await redisClient.zadd(`${RATE_LIMITER_CACHE_KEY}recordings`, 1, commonOrganizationId)
        const isEventsRateLimited = await rateLimiter.checkLimited('events', commonOrganizationId)
        const isRecordingsRateLimited = await rateLimiter.checkLimited('recordings', commonOrganizationId)
        expect(isEventsRateLimited).toBe(true)
        expect(isRecordingsRateLimited).toBe(true)
    })

    it('checks that the rate limiter is caching the org ids', async () => {
        const redisClient = await hub.db.redisPool.acquire()
        expect(await rateLimiter.checkLimited('events', commonOrganizationId)).toBe(false)
        expect(await rateLimiter.checkLimited('recordings', commonOrganizationId)).toBe(false)

        await redisClient.zadd(`${RATE_LIMITER_CACHE_KEY}events`, 1, commonOrganizationId)
        await redisClient.zadd(`${RATE_LIMITER_CACHE_KEY}recordings`, 1, commonOrganizationId)

        // should be cached and still return false
        expect(await rateLimiter.checkLimited('events', commonOrganizationId)).toBe(false)
        expect(await rateLimiter.checkLimited('recordings', commonOrganizationId)).toBe(false)

        jest.advanceTimersByTime(60000)
        expect(await rateLimiter.checkLimited('events', commonOrganizationId)).toBe(true)
        expect(await rateLimiter.checkLimited('recordings', commonOrganizationId)).toBe(true)
    })
})
