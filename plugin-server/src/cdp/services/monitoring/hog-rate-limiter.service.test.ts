import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { delay } from '~/utils/utils'

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

        const reallyAdvanceTime = async (ms: number) => {
            advanceTime(ms)
            await delay(ms)
        }

        afterEach(async () => {
            await closeHub(hub)
            jest.clearAllMocks()
        })

        it('should use tokens for an ID', async () => {
            const res = await rateLimiter.rateLimitMany({ [id1]: 1 })

            expect(res).toEqual({
                [id1]: {
                    tokens: 99,
                    isRateLimited: false,
                },
            })
        })

        it('should rate limit an ID', async () => {
            let res = await rateLimiter.rateLimitMany({ [id1]: 99 })

            expect(res[id1].tokens).toBe(1)
            expect(res[id1].isRateLimited).toBe(false)

            res = await rateLimiter.rateLimitMany({ [id1]: 1 })

            expect(res[id1].tokens).toBe(0)
            expect(res[id1].isRateLimited).toBe(true)

            res = await rateLimiter.rateLimitMany({ [id1]: 1 })

            expect(res[id1].tokens).toBe(99)
            expect(res[id1].isRateLimited).toBe(false)
        })

        it('should rate limit many IDs', async () => {
            const res = await rateLimiter.rateLimitMany({ [id1]: 1, [id2]: 5 })

            expect(res).toEqual({
                [id1]: {
                    tokens: 99,
                    isRateLimited: false,
                },
                [id2]: {
                    tokens: 95,
                    isRateLimited: false,
                },
            })

            const res2 = await rateLimiter.rateLimitMany({ [id1]: 1, [id2]: 0 })

            expect(res2).toEqual({
                [id1]: {
                    tokens: 98,
                    isRateLimited: false,
                },
                [id2]: {
                    tokens: 95,
                    isRateLimited: false,
                },
            })
        })

        // it('should refill over time', async () => {
        //     const res = await rateLimiter.rateLimitMany({ [id1]: 50 })

        //     expect(res[id1].tokens).toBe(50)
    })
})
