import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

// E2E for the ET team-global rate limit: 100 events per 15 minutes, sustained 10 ev/sec.
// Real Redis, real V4 lua, real per-input fan-out — proves that:
//   - the initial burst of 100 passes,
//   - sustained overload drains the bucket to ~0 and starves new events,
//   - refill accumulates cross-batch (fractional remainder preserved by minCost=1 floor),
//   - over the 15-minute window we admit roughly 100 + bucketSize = ~200 total
//     (one bucket worth burst + one bucket worth refill).
describe('error tracking — sustained traffic e2e', () => {
    jest.retryTimes(2)

    let now: number
    let hub: Hub
    let redis: RedisV2

    const advanceTime = (ms: number) => {
        now += ms
        mockNow.mockReturnValue(now)
    }

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
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    it('100 per 15min: bursts 100 immediately, then admits ~bucketSize more across the window', async () => {
        const bucketSize = 100
        const minutes = 15
        const refillRate = bucketSize / (minutes * 60) // ~0.111 / sec
        const limiter = new KeyedRateLimiterService(
            {
                name: 'et-e2e-sustained',
                bucketSize,
                refillRate,
                ttlSeconds: 60 * 60,
                overdraftEnabled: true,
                minCost: 1,
            },
            redis
        )
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

        const eventsPerSecond = 10
        const totalSeconds = minutes * 60
        const batchIntervalMs = 1000 / eventsPerSecond // 100ms between calls
        const batchSize = 1 // one event per call

        let totalAllowed = 0
        let firstBurstAllowed = 0
        let seenFirstStarve = false
        let allowedDuringFirstSecond = 0

        for (let i = 0; i < totalSeconds * eventsPerSecond; i++) {
            const elapsedMs = i * batchIntervalMs
            const requests = Array.from({ length: batchSize }, () => ({ id: 'team-1', cost: 1 }))
            const res = await limiter.rateLimitGrouped(requests)
            const allowed = res.filter(([, r]) => !r.isRateLimited).length
            totalAllowed += allowed
            if (elapsedMs < 1000) {
                allowedDuringFirstSecond += allowed
            }
            if (i < bucketSize) {
                firstBurstAllowed += allowed
            }
            if (i >= bucketSize && allowed === 0 && !seenFirstStarve) {
                seenFirstStarve = true
            }
            advanceTime(batchIntervalMs)
        }

        // Burst: the first 100 events (well within the first second) all pass.
        expect(firstBurstAllowed).toBe(bucketSize)
        // After the burst, the bucket drains to 0 and we're in sustained overdraft.
        expect(seenFirstStarve).toBe(true)
        // Over 15 minutes: bucketSize burst + bucketSize refill = 2 * bucketSize total.
        // Allow ±5 slack for JS scheduling jitter / boundary edge cases.
        expect(totalAllowed).toBeGreaterThanOrEqual(2 * bucketSize - 5)
        expect(totalAllowed).toBeLessThanOrEqual(2 * bucketSize + 5)
        // First second can only ever admit at most bucketSize + 1 refill (round-down):
        expect(allowedDuringFirstSecond).toBeLessThanOrEqual(bucketSize + 1)
    }, 30000)
})
