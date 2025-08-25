import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../_tests/redis'
import { CdpRedis, createCdpRedisPool } from '../../redis'
import { BASE_REDIS_KEY, HogRateLimiterService } from './hog-rate-limiter.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('HogRateLimiter', () => {
    jest.retryTimes(3)

    describe('integration', () => {
        let now: number
        let hub: Hub
        let rateLimiter: HogRateLimiterService
        let redis: CdpRedis
        const id1 = 'hog-function-id-1'
        const id2 = 'hog-function-id-2'

        beforeEach(async () => {
            hub = await createHub()
            now = 1720000000000
            mockNow.mockReturnValue(now)

            hub.CDP_RATE_LIMITER_BUCKET_SIZE = 100
            hub.CDP_RATE_LIMITER_REFILL_RATE = 10
            hub.CDP_RATE_LIMITER_TTL = 60 * 60 * 24

            redis = createCdpRedisPool(hub)
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

            rateLimiter = new HogRateLimiterService(hub, redis)
        })

        const advanceTime = (ms: number) => {
            now += ms
            mockNow.mockReturnValue(now)
        }

        afterEach(async () => {
            await closeHub(hub)
            jest.clearAllMocks()
        })

        it('should use tokens for an ID', async () => {
            const res = await rateLimiter.rateLimitMany([[id1, 1]])

            expect(res).toEqual([[id1, { tokens: 99, isRateLimited: false }]])
        })

        it('should rate limit an ID', async () => {
            let res = await rateLimiter.rateLimitMany([[id1, 99]])

            expect(res[0][1].tokens).toBe(1)
            expect(res[0][1].isRateLimited).toBe(false)

            res = await rateLimiter.rateLimitMany([[id1, 1]])

            expect(res[0][1].tokens).toBe(0)
            expect(res[0][1].isRateLimited).toBe(true)

            res = await rateLimiter.rateLimitMany([[id1, 20]])

            expect(res[0][1].tokens).toBe(-1) // It never goes below -1
            expect(res[0][1].isRateLimited).toBe(true)
        })

        it('should use tokens for many IDs', async () => {
            const res = await rateLimiter.rateLimitMany([
                [id1, 1],
                [id2, 5],
            ])

            expect(res).toEqual([
                [id1, { tokens: 99, isRateLimited: false }],
                [id2, { tokens: 95, isRateLimited: false }],
            ])

            const res2 = await rateLimiter.rateLimitMany([
                [id1, 1],
                [id2, 0],
            ])

            expect(res2).toEqual([
                [id1, { tokens: 98, isRateLimited: false }],
                [id2, { tokens: 95, isRateLimited: false }],
            ])
        })

        it('should refill over time', async () => {
            const res = await rateLimiter.rateLimitMany([[id1, 50]])

            expect(res[0][1].tokens).toBe(50)

            advanceTime(1000) // 1 second = 10 tokens

            const res2 = await rateLimiter.rateLimitMany([[id1, 5]])

            expect(res2[0][1].tokens).toBe(55) // cost 5 but added 10 tokens
            expect(res2[0][1].isRateLimited).toBe(false)

            advanceTime(4000) // 4 seconds = 40 tokens

            const res3 = await rateLimiter.rateLimitMany([[id1, 0]])

            expect(res3[0][1].tokens).toBe(95)
            expect(res3[0][1].isRateLimited).toBe(false)
        })

        it('should allow rate usage for multiple of the same ID', async () => {
            const res = await rateLimiter.rateLimitMany([
                [id1, 90],
                [id1, 9],
                [id1, 1],
                [id1, 2],
            ])

            expect(res).toEqual([
                [id1, { tokens: 10, isRateLimited: false }],
                [id1, { tokens: 1, isRateLimited: false }],
                [id1, { tokens: 0, isRateLimited: true }],
                [id1, { tokens: -1, isRateLimited: true }],
            ])
        })
    })
})
