import { deleteKeysWithPrefix } from '~/cdp/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'

import { MetricsIngestionConsumerConfig, getDefaultMetricsIngestionConsumerConfig } from '../config'
import { BASE_REDIS_KEY, MetricsRateLimiterService } from './metrics-rate-limiter.service'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

describe('MetricsRateLimiterService', () => {
    jest.retryTimes(3)
    const BUCKET_SIZE_KB = 10
    const BUCKET_EXCEEDED_UNCOMPRESSED_BYTES = 15360 // 15KB > 10KB bucket

    let config: MetricsIngestionConsumerConfig
    let rateLimiter: MetricsRateLimiterService
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
        mockNow.mockReturnValue(1720000000000)

        config = {
            ...getDefaultMetricsIngestionConsumerConfig(),
            METRICS_LIMITER_BUCKET_SIZE_KB: BUCKET_SIZE_KB,
            METRICS_LIMITER_REFILL_RATE_KB_PER_SECOND: 1,
            METRICS_LIMITER_TTL_SECONDS: 3600,
            METRICS_LIMITER_ENABLED_TEAMS: '*',
            METRICS_LIMITER_DISABLED_FOR_TEAMS: '',
            METRICS_LIMITER_EXEMPT_TEAMS: '',
            METRICS_LIMITER_TEAM_BUCKET_SIZE_KB: '',
            METRICS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND: '',
        }

        redis = createRedisV2PoolFromConfig({
            connection: {
                url: config.METRICS_REDIS_HOST,
                options: { port: config.METRICS_REDIS_PORT, tls: config.METRICS_REDIS_TLS ? {} : undefined },
            },
            poolMinSize: config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        })
        await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)

        rateLimiter = new MetricsRateLimiterService(config, redis)
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('filterMessages', () => {
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

        it('should skip rate limiting when METRICS_LIMITER_ENABLED_TEAMS is empty', async () => {
            config.METRICS_LIMITER_ENABLED_TEAMS = ''
            rateLimiter = new MetricsRateLimiterService(config, redis)

            const messages = [createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES)]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.dropped).toHaveLength(0)
        })
    })

    describe('exemption (METRICS_LIMITER_EXEMPT_TEAMS)', () => {
        it('should keep throttling unchanged when the exemption list is empty', async () => {
            const messages = [createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES)]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(0)
            expect(result.dropped).toHaveLength(1)
        })

        it('should always allow exempt teams while still throttling non-exempt teams', async () => {
            config.METRICS_LIMITER_EXEMPT_TEAMS = '1'
            rateLimiter = new MetricsRateLimiterService(config, redis)

            const messages = [
                createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES), // exempt - allowed despite exceeding bucket
                createMessage(2, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES), // not exempt - dropped
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(1)
            expect(result.allowed[0].teamId).toBe(1)
            expect(result.dropped).toHaveLength(1)
            expect(result.dropped[0].teamId).toBe(2)
        })

        it('should prioritize METRICS_LIMITER_EXEMPT_TEAMS over METRICS_LIMITER_ENABLED_TEAMS', async () => {
            config.METRICS_LIMITER_ENABLED_TEAMS = '1, 2'
            config.METRICS_LIMITER_EXEMPT_TEAMS = '1'
            rateLimiter = new MetricsRateLimiterService(config, redis)

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

        it('should exempt all teams when METRICS_LIMITER_EXEMPT_TEAMS is *', async () => {
            config.METRICS_LIMITER_EXEMPT_TEAMS = '*'
            rateLimiter = new MetricsRateLimiterService(config, redis)

            const messages = [
                createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
                createMessage(2, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES),
            ]

            const result = await rateLimiter.filterMessages(messages)

            expect(result.allowed).toHaveLength(2)
            expect(result.dropped).toHaveLength(0)
        })

        it('should not consume tokens for exempt teams', async () => {
            config.METRICS_LIMITER_EXEMPT_TEAMS = '1'
            rateLimiter = new MetricsRateLimiterService(config, redis)

            const result = await rateLimiter.filterMessages([createMessage(1, BUCKET_EXCEEDED_UNCOMPRESSED_BYTES)])
            expect(result.allowed).toHaveLength(1)

            // The exempt traffic must not have touched team 1's token bucket: a limiter
            // without the exemption should still see a full bucket for that team.
            config.METRICS_LIMITER_EXEMPT_TEAMS = ''
            rateLimiter = new MetricsRateLimiterService(config, redis)

            const [[, limit]] = await rateLimiter.rateLimitMany([['1', 0, Math.round(Date.now() / 1000)]])
            expect(limit.tokensBefore).toBe(BUCKET_SIZE_KB)
        })

        it.each([
            { exemptConfig: '', teamId: 2, expected: false, description: 'empty list exempts nobody' },
            { exemptConfig: '2', teamId: 2, expected: true, description: 'single team match' },
            { exemptConfig: '2', teamId: 3, expected: false, description: 'single team non-match' },
            { exemptConfig: '1, 2', teamId: 2, expected: true, description: 'multiple teams with spaces' },
            { exemptConfig: '*', teamId: 99, expected: true, description: 'wildcard exempts everyone' },
            { exemptConfig: 'abc', teamId: 2, expected: false, description: 'malformed entry is ignored' },
        ])('isTeamExempt: $description', ({ exemptConfig, teamId, expected }) => {
            config.METRICS_LIMITER_EXEMPT_TEAMS = exemptConfig
            rateLimiter = new MetricsRateLimiterService(config, redis)

            expect(rateLimiter.isTeamExempt(teamId)).toBe(expected)
        })
    })
})
