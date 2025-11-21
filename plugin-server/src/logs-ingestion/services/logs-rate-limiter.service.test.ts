import { deleteKeysWithPrefix } from '~/cdp/_tests/redis'
import { RedisV2, createRedisV2Pool } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { BASE_REDIS_KEY, LogsRateLimiterService } from './logs-rate-limiter.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('LogsRateLimiterService', () => {
    jest.retryTimes(3)

    describe('integration', () => {
        let now: number
        let hub: Hub
        let rateLimiter: LogsRateLimiterService
        let redis: RedisV2
        const teamId1 = 'team-1'
        const teamId2 = 'team-2'

        beforeEach(async () => {
            hub = await createHub()
            now = 1720000000000
            mockNow.mockReturnValue(now)

            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 100
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 10
            hub.LOGS_LIMITER_TTL_SECONDS = 60 * 60 * 24

            redis = createRedisV2Pool(hub, 'logs')
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

            rateLimiter = new LogsRateLimiterService(hub, redis)
        })

        const advanceTime = (ms: number) => {
            now += ms
            mockNow.mockReturnValue(now)
        }

        afterEach(async () => {
            await closeHub(hub)
            jest.clearAllMocks()
        })

        it('should consume tokens and return before/after values', async () => {
            const res = await rateLimiter.rateLimitMany([[teamId1, 10]])

            expect(res).toEqual([[teamId1, { tokensBefore: 100, tokensAfter: 90, isRateLimited: false }]])
        })

        it('should rate limit when tokens are exhausted', async () => {
            let res = await rateLimiter.rateLimitMany([[teamId1, 99]])

            expect(res[0][1].tokensBefore).toBe(100)
            expect(res[0][1].tokensAfter).toBe(1)
            expect(res[0][1].isRateLimited).toBe(false)

            res = await rateLimiter.rateLimitMany([[teamId1, 1]])

            expect(res[0][1].tokensBefore).toBe(1)
            expect(res[0][1].tokensAfter).toBe(0)
            expect(res[0][1].isRateLimited).toBe(true)

            res = await rateLimiter.rateLimitMany([[teamId1, 20]])

            expect(res[0][1].tokensBefore).toBe(0)
            expect(res[0][1].tokensAfter).toBe(-1)
            expect(res[0][1].isRateLimited).toBe(true)
        })

        it('should allow partial allowance calculation from tokensBefore', async () => {
            // First exhaust most of the bucket
            await rateLimiter.rateLimitMany([[teamId1, 70]])

            // Request 50KB but only 30KB available - tokensBefore tells us how much to allow
            const res = await rateLimiter.rateLimitMany([[teamId1, 50]])

            expect(res[0][1].tokensBefore).toBe(30)
            expect(res[0][1].tokensAfter).toBe(-1)
            expect(res[0][1].isRateLimited).toBe(true)

            // Can calculate: allow 30KB out of 50KB requested (60%)
            const allowedKb = res[0][1].tokensBefore
            const requestedKb = 50
            const allowanceRatio = allowedKb / requestedKb
            expect(allowanceRatio).toBe(0.6)
        })

        it('should handle multiple teams independently', async () => {
            const res = await rateLimiter.rateLimitMany([
                [teamId1, 10],
                [teamId2, 50],
            ])

            expect(res).toEqual([
                [teamId1, { tokensBefore: 100, tokensAfter: 90, isRateLimited: false }],
                [teamId2, { tokensBefore: 100, tokensAfter: 50, isRateLimited: false }],
            ])

            const res2 = await rateLimiter.rateLimitMany([
                [teamId1, 5],
                [teamId2, 0],
            ])

            expect(res2).toEqual([
                [teamId1, { tokensBefore: 90, tokensAfter: 85, isRateLimited: false }],
                [teamId2, { tokensBefore: 50, tokensAfter: 50, isRateLimited: false }],
            ])
        })

        it('should refill tokens over time at configured rate', async () => {
            const res = await rateLimiter.rateLimitMany([[teamId1, 50]])

            expect(res[0][1].tokensBefore).toBe(100)
            expect(res[0][1].tokensAfter).toBe(50)

            advanceTime(1000) // 1 second = 10KB refilled

            const res2 = await rateLimiter.rateLimitMany([[teamId1, 5]])

            expect(res2[0][1].tokensBefore).toBe(60) // 50 + 10 refilled
            expect(res2[0][1].tokensAfter).toBe(55)
            expect(res2[0][1].isRateLimited).toBe(false)

            advanceTime(4000) // 4 seconds = 40KB refilled

            const res3 = await rateLimiter.rateLimitMany([[teamId1, 0]])

            expect(res3[0][1].tokensBefore).toBe(95) // 55 + 40, capped at 100
            expect(res3[0][1].tokensAfter).toBe(95)
            expect(res3[0][1].isRateLimited).toBe(false)
        })

        it('should not refill above bucket size', async () => {
            const res = await rateLimiter.rateLimitMany([[teamId1, 10]])

            expect(res[0][1].tokensAfter).toBe(90)

            advanceTime(5000) // 5 seconds = 50KB refilled, but capped at 100

            const res2 = await rateLimiter.rateLimitMany([[teamId1, 0]])

            expect(res2[0][1].tokensBefore).toBe(100) // capped at bucket size
            expect(res2[0][1].tokensAfter).toBe(100)
        })

        it('should handle sequential requests for same team in single call', async () => {
            const res = await rateLimiter.rateLimitMany([
                [teamId1, 90],
                [teamId1, 9],
                [teamId1, 1],
                [teamId1, 2],
            ])

            expect(res).toEqual([
                [teamId1, { tokensBefore: 100, tokensAfter: 10, isRateLimited: false }],
                [teamId1, { tokensBefore: 10, tokensAfter: 1, isRateLimited: false }],
                [teamId1, { tokensBefore: 1, tokensAfter: 0, isRateLimited: true }],
                [teamId1, { tokensBefore: 0, tokensAfter: -1, isRateLimited: true }],
            ])
        })

        it('should handle zero cost requests', async () => {
            const res = await rateLimiter.rateLimitMany([[teamId1, 0]])

            expect(res).toEqual([[teamId1, { tokensBefore: 100, tokensAfter: 100, isRateLimited: false }]])
        })

        it('should recover from negative pool over time', async () => {
            // Exhaust the bucket completely
            await rateLimiter.rateLimitMany([[teamId1, 100]])
            const res = await rateLimiter.rateLimitMany([[teamId1, 50]])

            expect(res[0][1].tokensBefore).toBe(0)
            expect(res[0][1].tokensAfter).toBe(-1)

            // Wait for refill (2 seconds = 20KB)
            advanceTime(2000)

            const res2 = await rateLimiter.rateLimitMany([[teamId1, 0]])

            // Pool was -1, refills by 20, so now 19
            expect(res2[0][1].tokensBefore).toBe(19)
            expect(res2[0][1].tokensAfter).toBe(19)
            expect(res2[0][1].isRateLimited).toBe(false)
        })

        it('should handle cost exceeding bucket size on first request', async () => {
            const res = await rateLimiter.rateLimitMany([[teamId1, 200]])

            expect(res[0][1].tokensBefore).toBe(100)
            expect(res[0][1].tokensAfter).toBe(-1)
            expect(res[0][1].isRateLimited).toBe(true)
        })

        it('should not refill within same second', async () => {
            const res = await rateLimiter.rateLimitMany([[teamId1, 50]])

            expect(res[0][1].tokensAfter).toBe(50)

            // Advance less than 1 second (use 400ms to avoid rounding to next second)
            advanceTime(400)

            const res2 = await rateLimiter.rateLimitMany([[teamId1, 0]])

            // No refill should occur
            expect(res2[0][1].tokensBefore).toBe(50)
            expect(res2[0][1].tokensAfter).toBe(50)
        })
    })
})
