import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

// E2E for the ET team-global rate limit: 100 events per 15 minutes, sustained 10 ev/sec.
// Real Redis, real V3 lua (post floor-drain fix), real per-input fan-out — proves that:
//   - the initial burst of 100 passes,
//   - sustained overload drains the bucket to ~0 and starves new events,
//   - refill accumulates cross-batch (V3 lua's floor-drain preserves the fractional remainder),
//   - over the 15-minute window we admit roughly bucketSize burst + bucketSize refill (~2x bucketSize).
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
            { name: 'et-e2e-sustained', bucketSize, refillRate, ttlSeconds: 60 * 60 },
            redis
        )
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())

        // Sustained 10 ev/sec as one batch of 10 per second — same fan-out as 10
        // singleton calls but 10× fewer Redis round-trips.
        const eventsPerBatch = 10
        const totalSeconds = minutes * 60
        const batchIntervalMs = 1000

        let totalAllowed = 0
        let firstBurstAllowed = 0
        let seenFirstStarve = false

        for (let s = 0; s < totalSeconds; s++) {
            const res = await limiter.rateLimitGrouped(
                Array.from({ length: eventsPerBatch }, () => ({ id: 'team-1', cost: 1 }))
            )
            const allowed = res.filter(([, r]) => !r.isRateLimited).length
            totalAllowed += allowed
            // The first ten seconds carry the burst (bucketSize=100 / eventsPerBatch=10).
            if (s < bucketSize / eventsPerBatch) {
                firstBurstAllowed += allowed
            }
            if (s >= bucketSize / eventsPerBatch && allowed === 0 && !seenFirstStarve) {
                seenFirstStarve = true
            }
            advanceTime(batchIntervalMs)
        }

        // The first bucketSize events all pass (initial burst).
        expect(firstBurstAllowed).toBe(bucketSize)
        // After the burst, the bucket drains and we hit the starvation window.
        expect(seenFirstStarve).toBe(true)
        // Over 15 minutes: bucketSize burst + bucketSize refill = 2 × bucketSize total.
        // Allow ±5 slack for fractional boundary edge cases.
        expect(totalAllowed).toBeGreaterThanOrEqual(2 * bucketSize - 5)
        expect(totalAllowed).toBeLessThanOrEqual(2 * bucketSize + 5)
    }, 30000)
})
