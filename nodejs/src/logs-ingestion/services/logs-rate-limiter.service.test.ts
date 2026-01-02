import { deleteKeysWithPrefix } from '~/cdp/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { BASE_REDIS_KEY, LogsRateLimiterService } from './logs-rate-limiter.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('LogsRateLimiterService', () => {
    jest.retryTimes(3)
    const LOGS_LIMITER_BUCKET_SIZE_KB = 100
    const BUCKET_EXCEEDED_UNCOMPRESSED_BYTES = 15360

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

            hub.LOGS_LIMITER_BUCKET_SIZE_KB = LOGS_LIMITER_BUCKET_SIZE_KB
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 10
            hub.LOGS_LIMITER_TTL_SECONDS = 60 * 60 * 24

            redis = createRedisV2PoolFromConfig({
                connection: hub.LOGS_REDIS_HOST
                    ? {
                          url: hub.LOGS_REDIS_HOST,
                          options: { port: hub.LOGS_REDIS_PORT, tls: hub.LOGS_REDIS_TLS ? {} : undefined },
                      }
                    : { url: hub.REDIS_URL },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            })
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

    describe('filterMessages', () => {
        let hub: Hub
        let rateLimiter: LogsRateLimiterService
        let redis: RedisV2

        const createMessage = (teamId: number, bytesUncompressed: number): any => ({
            teamId,
            bytesUncompressed,
            bytesCompressed: Math.floor(bytesUncompressed / 2),
            recordCount: 1,
            token: `token-${teamId}`,
            message: { value: Buffer.from('test') },
        })

        beforeEach(async () => {
            hub = await createHub()
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = 10
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = 1
            hub.LOGS_LIMITER_TTL_SECONDS = 3600
            hub.LOGS_LIMITER_ENABLED_TEAMS = '*'

            redis = createRedisV2PoolFromConfig({
                connection: hub.LOGS_REDIS_HOST
                    ? {
                          url: hub.LOGS_REDIS_HOST,
                          options: { port: hub.LOGS_REDIS_PORT, tls: hub.LOGS_REDIS_TLS ? {} : undefined },
                      }
                    : { url: hub.REDIS_URL },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            })
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

            rateLimiter = new LogsRateLimiterService(hub, redis)
        })

        afterEach(async () => {
            await closeHub(hub)
        })

        it('should allow messages within bucket size', async () => {
            const messages = [createMessage(1, 5120), createMessage(1, 3072)] // 5KB + 3KB = 8KB < 10KB

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(2)
            expect(result.dropped).toHaveLength(0)
        })

        it('should drop messages exceeding bucket size', async () => {
            const messages = [createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES)] // 15KB > 10KB

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(0)
            expect(result.dropped).toHaveLength(1)
        })

        it('should allow partial batch through', async () => {
            const messages = [
                createMessage(1, 5120), // 5KB - allowed
                createMessage(1, 6144), // 6KB - dropped (5+6=11 > 10)
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.allowed[0].bytesUncompressed).toBe(5120)
            expect(result.dropped).toHaveLength(1)
            expect(result.dropped[0].bytesUncompressed).toBe(6144)
        })

        it('should rate limit teams independently', async () => {
            const messages = [
                createMessage(1, 15360), // Team 1: 15KB - dropped
                createMessage(2, 5120), // Team 2: 5KB - allowed
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.allowed[0].teamId).toBe(2)
            expect(result.dropped).toHaveLength(1)
            expect(result.dropped[0].teamId).toBe(1)
        })

        it('should skip rate limiting for teams not in LOGS_LIMITER_ENABLED_TEAMS', async () => {
            hub.LOGS_LIMITER_ENABLED_TEAMS = '2' // Only team 2
            rateLimiter = new LogsRateLimiterService(hub, redis)

            const messages = [
                createMessage(1, 15360), // Team 1: 15KB - allowed (not rate limited)
                createMessage(2, 15360), // Team 2: 15KB - dropped (rate limited)
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.allowed[0].teamId).toBe(1)
            expect(result.dropped).toHaveLength(1)
            expect(result.dropped[0].teamId).toBe(2)
        })

        it('should skip rate limiting when LOGS_LIMITER_ENABLED_TEAMS is empty', async () => {
            hub.LOGS_LIMITER_ENABLED_TEAMS = ''
            rateLimiter = new LogsRateLimiterService(hub, redis)

            const messages = [createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES)]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.dropped).toHaveLength(0)
        })

        it('should rate limit all teams when LOGS_LIMITER_ENABLED_TEAMS is *', async () => {
            hub.LOGS_LIMITER_ENABLED_TEAMS = '*'

            const messages = [createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES)]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(0)
            expect(result.dropped).toHaveLength(1)
        })

        it('should handle multiple teams in LOGS_LIMITER_ENABLED_TEAMS', async () => {
            hub.LOGS_LIMITER_ENABLED_TEAMS = '1, 3' // Teams 1 and 3
            rateLimiter = new LogsRateLimiterService(hub, redis)

            const messages = [
                createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES), // Team 1: dropped (rate limited)
                createMessage(2, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES), // Team 2: allowed (not in list)
                createMessage(3, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES), // Team 3: dropped (rate limited)
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.allowed[0].teamId).toBe(2)
            expect(result.dropped).toHaveLength(2)
        })

        it('should skip rate limiting for all teams when LOGS_LIMITER_DISABLED_FOR_TEAMS is *', async () => {
            hub.LOGS_LIMITER_ENABLED_TEAMS = '*'
            hub.LOGS_LIMITER_DISABLED_FOR_TEAMS = '*'
            rateLimiter = new LogsRateLimiterService(hub, redis)

            const messages = [
                createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
                createMessage(2, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
                createMessage(3, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(3)
            expect(result.dropped).toHaveLength(0)
        })

        it('should skip rate limiting for specific teams in LOGS_LIMITER_DISABLED_FOR_TEAMS', async () => {
            hub.LOGS_LIMITER_ENABLED_TEAMS = '*'
            hub.LOGS_LIMITER_DISABLED_FOR_TEAMS = '1, 3'
            rateLimiter = new LogsRateLimiterService(hub, redis)

            const messages = [
                createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
                createMessage(2, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
                createMessage(3, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(2)
            expect(result.allowed.map((m) => m.teamId)).toEqual([1, 3])
            expect(result.dropped).toHaveLength(1)
            expect(result.dropped[0].teamId).toBe(2)
        })

        it('should prioritize LOGS_LIMITER_DISABLED_FOR_TEAMS over LOGS_LIMITER_ENABLED_TEAMS', async () => {
            hub.LOGS_LIMITER_ENABLED_TEAMS = '1, 2'
            hub.LOGS_LIMITER_DISABLED_FOR_TEAMS = '1'
            rateLimiter = new LogsRateLimiterService(hub, redis)

            const messages = [
                createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
                createMessage(2, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.allowed[0].teamId).toBe(1)
            expect(result.dropped).toHaveLength(1)
            expect(result.dropped[0].teamId).toBe(2)
        })

        it('should handle zero byte messages', async () => {
            const messages = [createMessage(1, 0)]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.dropped).toHaveLength(0)
        })
    })

    describe('team-specific limits', () => {
        let hub: Hub
        let redis: RedisV2

        const DEFAULT_BUCKET_SIZE_KB = 100
        const DEFAULT_REFILL_RATE_KB_PER_SECOND = 10

        beforeEach(async () => {
            hub = await createHub()
            hub.LOGS_LIMITER_BUCKET_SIZE_KB = DEFAULT_BUCKET_SIZE_KB
            hub.LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND = DEFAULT_REFILL_RATE_KB_PER_SECOND
            hub.LOGS_LIMITER_TTL_SECONDS = 3600
            hub.LOGS_LIMITER_ENABLED_TEAMS = '*'

            redis = createRedisV2PoolFromConfig({
                connection: hub.LOGS_REDIS_HOST
                    ? {
                          url: hub.LOGS_REDIS_HOST,
                          options: { port: hub.LOGS_REDIS_PORT, tls: hub.LOGS_REDIS_TLS ? {} : undefined },
                      }
                    : { url: hub.REDIS_URL },
                poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
            })
            await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
        })

        afterEach(async () => {
            await closeHub(hub)
        })

        it.each([
            { config: '1:50', teamId: '1', expectedBucket: 50, description: 'team with override' },
            {
                config: '1:50',
                teamId: '2',
                expectedBucket: DEFAULT_BUCKET_SIZE_KB,
                description: 'team without override',
            },
            { config: '1:25, 2:50, 3:75', teamId: '1', expectedBucket: 25, description: 'first of multiple overrides' },
            { config: '1:25, 2:50, 3:75', teamId: '3', expectedBucket: 75, description: 'last of multiple overrides' },
            { config: '', teamId: '1', expectedBucket: DEFAULT_BUCKET_SIZE_KB, description: 'empty config' },
        ])('uses correct bucket size for $description', async ({ config, teamId, expectedBucket }) => {
            hub.LOGS_LIMITER_TEAM_BUCKET_SIZE_KB = config
            const rateLimiter = new LogsRateLimiterService(hub, redis)

            const [[, result]] = await rateLimiter.rateLimitMany([[teamId, 0]])

            expect(result.tokensBefore).toBe(expectedBucket)
        })

        it.each([
            { config: '1:5', teamId: '1', expectedRefill: 10, description: 'team with 5KB/s override' },
            { config: '1:5', teamId: '2', expectedRefill: 20, description: 'team using default 10KB/s' },
        ])('uses correct refill rate for $description', async ({ config, teamId, expectedRefill }) => {
            hub.LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND = config
            const rateLimiter = new LogsRateLimiterService(hub, redis)

            await rateLimiter.rateLimitMany([[teamId, 50]])
            mockNow.mockReturnValue(Date.now() + 2000)
            const [[, result]] = await rateLimiter.rateLimitMany([[teamId, 0]])

            expect(result.tokensBefore).toBe(50 + expectedRefill)
        })

        it.each([
            { config: 'invalid', teamId: '1', description: 'completely invalid' },
            { config: '2:abc', teamId: '2', description: 'non-numeric value' },
            { config: ':100', teamId: '1', description: 'missing team id' },
            { config: '3:', teamId: '3', description: 'missing value' },
        ])('falls back to default for malformed config: $description', async ({ config, teamId }) => {
            hub.LOGS_LIMITER_TEAM_BUCKET_SIZE_KB = config
            const rateLimiter = new LogsRateLimiterService(hub, redis)

            const [[, result]] = await rateLimiter.rateLimitMany([[teamId, 0]])

            expect(result.tokensBefore).toBe(DEFAULT_BUCKET_SIZE_KB)
        })
    })
})
