import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../_tests/redis'
import { BASE_REDIS_KEY, HogRateLimiterService } from './hog-rate-limiter.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('HogRateLimiter', () => {
    jest.retryTimes(3)

    describe('integration', () => {
        let now: number
        let hub: Hub
        let rateLimiter: HogRateLimiterService
        let redis: RedisV2
        const id1 = 'hog-function-id-1'
        const id2 = 'hog-function-id-2'

        beforeEach(async () => {
            hub = await createHub()
            now = 1720000000000
            mockNow.mockReturnValue(now)

            redis = createRedisV2PoolFromConfig({
                connection: hub.CDP_REDIS_HOST
                    ? {
                          url: hub.CDP_REDIS_HOST,
                          options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                      }
                    : { url: hub.REDIS_URL },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            })
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

            rateLimiter = new HogRateLimiterService(
                { bucketSize: 100, refillRate: 10, ttl: 60 * 60 * 24, deferredGraceMs: 0 },
                redis
            )
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

        describe('tryDefer', () => {
            const flowId = 'flow-a'
            const otherFlowId = 'flow-b'

            it('should accept the first defer and schedule one refill-interval ahead', async () => {
                const res = await rateLimiter.tryDefer(flowId, 'inv-1', 100)

                // refillRate=10 -> one interval = 1000/10 = 100ms
                expect(res).toEqual({ accepted: true, scheduledAtMs: now + 100 })
            })

            it('should stagger concurrent defers by the refill interval', async () => {
                const first = await rateLimiter.tryDefer(flowId, 'inv-1', 100)
                const second = await rateLimiter.tryDefer(flowId, 'inv-2', 100)
                const third = await rateLimiter.tryDefer(flowId, 'inv-3', 100)

                expect(first.scheduledAtMs).toBe(now + 100)
                expect(second.scheduledAtMs).toBe(now + 200)
                expect(third.scheduledAtMs).toBe(now + 300)
            })

            it.each([
                { max: 1, attempts: 1, expectedAcceptedCount: 1 },
                { max: 3, attempts: 3, expectedAcceptedCount: 3 },
                { max: 3, attempts: 5, expectedAcceptedCount: 3 },
                { max: 10, attempts: 15, expectedAcceptedCount: 10 },
            ])(
                'accepts up to the cap ($expectedAcceptedCount/$attempts with max=$max)',
                async ({ max, attempts, expectedAcceptedCount }) => {
                    const results: boolean[] = []
                    for (let i = 0; i < attempts; i++) {
                        const res = await rateLimiter.tryDefer(flowId, `inv-${i}`, max)
                        results.push(res.accepted)
                    }

                    const accepted = results.filter((r) => r).length
                    expect(accepted).toBe(expectedAcceptedCount)
                }
            )

            it('returns accepted=false with scheduledAtMs=0 when the backlog is full', async () => {
                // Fill the backlog exactly
                await rateLimiter.tryDefer(flowId, 'inv-1', 2)
                await rateLimiter.tryDefer(flowId, 'inv-2', 2)

                const rejected = await rateLimiter.tryDefer(flowId, 'inv-3', 2)

                expect(rejected).toEqual({ accepted: false, scheduledAtMs: 0 })
            })

            it('releases capacity as scheduled times pass', async () => {
                // Queue 3 defers. At refillRate=10, these schedule at +100, +200, +300 ms.
                await rateLimiter.tryDefer(flowId, 'inv-1', 3)
                await rateLimiter.tryDefer(flowId, 'inv-2', 3)
                await rateLimiter.tryDefer(flowId, 'inv-3', 3)

                // Full backlog -> next defer is rejected
                const rejected = await rateLimiter.tryDefer(flowId, 'inv-4', 3)
                expect(rejected.accepted).toBe(false)

                // Advance past the first two scheduled times, which should auto-clean them
                advanceTime(250)

                const res = await rateLimiter.tryDefer(flowId, 'inv-5', 3)
                // Only the third entry remains pending, so this one takes position 2
                expect(res).toEqual({ accepted: true, scheduledAtMs: now + 200 })
            })

            it.each([
                { aDefers: 1, bDefers: 1 },
                { aDefers: 5, bDefers: 2 },
                { aDefers: 10, bDefers: 10 },
            ])(
                'tracks deferred backlog independently per flow (a=$aDefers, b=$bDefers)',
                async ({ aDefers, bDefers }) => {
                    for (let i = 0; i < aDefers; i++) {
                        const res = await rateLimiter.tryDefer(flowId, `a-${i}`, aDefers)
                        expect(res.accepted).toBe(true)
                    }

                    // Other flow still has full capacity
                    for (let i = 0; i < bDefers; i++) {
                        const res = await rateLimiter.tryDefer(otherFlowId, `b-${i}`, bDefers)
                        expect(res.accepted).toBe(true)
                    }

                    // Flow A is at cap
                    const overflow = await rateLimiter.tryDefer(flowId, 'a-over', aDefers)
                    expect(overflow.accepted).toBe(false)
                }
            )

            it('is idempotent for the same invocationId (re-adding updates score instead of growing backlog)', async () => {
                const first = await rateLimiter.tryDefer(flowId, 'inv-same', 2)
                expect(first.accepted).toBe(true)

                // Same invocationId again should not consume a new slot since it's a sorted set member
                const second = await rateLimiter.tryDefer(flowId, 'inv-same', 2)
                expect(second.accepted).toBe(true)

                // There should still be room for one more distinct invocation
                const third = await rateLimiter.tryDefer(flowId, 'inv-other', 2)
                expect(third.accepted).toBe(true)

                // And then the next one hits the cap
                const fourth = await rateLimiter.tryDefer(flowId, 'inv-reject', 2)
                expect(fourth.accepted).toBe(false)
            })
        })
    })
})
