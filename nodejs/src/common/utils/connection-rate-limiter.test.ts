import { getDefaultCommonConfig } from '~/common/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'

import { ConnectionRateLimiter } from './connection-rate-limiter'

const config = getDefaultCommonConfig()

describe('ConnectionRateLimiter', () => {
    let redis: RedisV2

    beforeEach(async () => {
        jest.spyOn(Date, 'now').mockReturnValue(1_767_225_600_000)
        redis = createRedisV2PoolFromConfig({ connection: { url: config.REDIS_URL }, poolMinSize: 1, poolMaxSize: 2 })
        await deleteKeysWithPrefix(redis, '@posthog/new-connections/')
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('shares one budget per address across pods, then refills at the configured rate', async () => {
        const options = { perSecond: 2, burst: 3 }
        const [podA, podB] = [new ConnectionRateLimiter(redis, options), new ConnectionRateLimiter(redis, options)]

        expect(await podA.tryTake(['1.1.1.1', '2.2.2.2'])).toEqual([true, true])
        expect(await podB.tryTake(['1.1.1.1'])).toEqual([true])
        expect(await podA.tryTake(['1.1.1.1'])).toEqual([true])
        expect(await podB.tryTake(['1.1.1.1', '2.2.2.2'])).toEqual([false, true])

        jest.spyOn(Date, 'now').mockReturnValue(1_767_225_601_000)
        expect(await podA.tryTake(['1.1.1.1'])).toEqual([true])
        expect(await podB.tryTake(['1.1.1.1'])).toEqual([true])
        expect(await podA.tryTake(['1.1.1.1'])).toEqual([false])
    })

    it('lets every connection through when Redis does not answer', async () => {
        // The error a real pool throws when it cannot hand out a client before the deadline.
        const unreachable = {
            usePipeline: () => Promise.reject(new Error('Redis pool redis: acquisition passed its deadline')),
        } as unknown as RedisV2
        const limiter = new ConnectionRateLimiter(unreachable, { perSecond: 1, burst: 1 })

        expect(await limiter.tryTake(['1.1.1.1', '1.1.1.1'])).toEqual([true, true])
    })
})
