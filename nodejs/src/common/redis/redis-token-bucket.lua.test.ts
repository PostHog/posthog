import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

type CommandName = 'checkRateLimit' | 'checkRateLimitV2' | 'checkRateLimitV3'

describe('redis-token-bucket lua', () => {
    jest.retryTimes(3)

    let now: number
    let hub: Hub
    let redis: RedisV2

    const advanceTime = (ms: number) => {
        now += ms
        mockNow.mockReturnValue(now)
    }

    const nowSeconds = () => Math.round(Date.now() / 1000)

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

    const callRateLimit = async ({
        command,
        key,
        cost,
        poolMax,
        fillRate,
    }: {
        command: CommandName
        key: string
        cost: number
        poolMax: number
        fillRate: number
    }): Promise<[number, number]> => {
        const result = await redis.useClient({ name: 'lua-test' }, async (client) => {
            return (await (client[command] as any)(key, nowSeconds(), cost, poolMax, fillRate, 60)) as
                | [number, number]
                | [string, string]
        })
        if (!result) {
            throw new Error(`expected ${command} result`)
        }
        return [Number(result[0]), Number(result[1])]
    }

    describe.each<{ command: CommandName; expectsRecovery: boolean }>([
        { command: 'checkRateLimit', expectsRecovery: false },
        { command: 'checkRateLimitV2', expectsRecovery: false },
        { command: 'checkRateLimitV3', expectsRecovery: true },
    ])('$command', ({ command, expectsRecovery }) => {
        it('refill=1.5/s cost=1 1req/s starting in overdraft — recovers (V3) or stays denied (V1/V2)', async () => {
            const key = `@posthog-test/lua-bucket/${command}/team-1`
            await deleteKeysWithPrefix(redis, key)

            let tokensAfterA = 0
            // here we are putting the bucket in overdraft. We send 100 requests with cost 1 to a 10 token bucket
            // after this, bucket reaches its "minimum state"
            for (let i = 0; i < 100; i++) {
                const [, tokensAfterTemp] = await callRateLimit({
                    command,
                    key,
                    cost: 1,
                    poolMax: 10,
                    fillRate: 1.5,
                })
                tokensAfterA = tokensAfterTemp
            }

            // v1/v2 and v3 have different minimum states
            if (expectsRecovery) {
                // v3 never goes below 0
                expect(tokensAfterA).toBe(0)
            } else {
                // v1/v2 goes below 0
                expect(tokensAfterA).toBe(-1)
            }

            let tokensAfterB = 0

            // here we are simulating a sustained traffic pattern
            // 1 request with cost 1 every second to a 1.5 token refill rate bucket
            // in theory it should recover
            for (let i = 0; i < 10; i++) {
                advanceTime(1000)
                const [, tokensAfterTemp] = await callRateLimit({ command, key, cost: 1, poolMax: 10, fillRate: 1.5 })
                tokensAfterB = tokensAfterTemp
            }

            if (expectsRecovery) {
                // and v3 does recover
                expect(tokensAfterB).toBeGreaterThan(0)
            } else {
                // but v1/v2 doesn't recover
                expect(tokensAfterB).toBe(-1)
            }
        })
    })
})
