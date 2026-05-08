import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'

const mockNow: jest.SpyInstance = jest.spyOn(Date, 'now')

// All three commands share the same arg shape; the only thing that varies is
// the Lua body. We test each by name so a regression in any version is loud.
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
            // V1's typing claims `Promise<number>` but the underlying Lua is identical
            // to V2 and returns [tokensBefore, tokensAfter]. V3 returns strings to
            // preserve fractional balances. Normalise both to numbers.
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
            // Each tick we earn 1.5 tokens and spend 1 → net +0.5/tick.
            // V1/V2 (charge-first) clamp every overdraft to -1 and throw the +0.5
            // away each tick → wedged forever.
            // V3 (check-first) refuses the initial cost=101 request without
            // charging, so the bucket stays at 100 and serves cost=1 every tick.
            const key = `@posthog-test/lua-bucket/${command}/team-1`
            await deleteKeysWithPrefix(redis, key)

            const [, tokensAfterFirstCall] = await callRateLimit({
                command,
                key,
                cost: 100,
                poolMax: 100,
                fillRate: 1.5,
            })
            expect(tokensAfterFirstCall).toBe(0)

            let tokensAfter = tokensAfterFirstCall
            for (let i = 0; i < 10; i++) {
                advanceTime(1000)
                const [, tokensAfterTemp] = await callRateLimit({ command, key, cost: 1, poolMax: 100, fillRate: 1.5 })
                tokensAfter = tokensAfterTemp
            }

            if (expectsRecovery) {
                expect(tokensAfter).toBeGreaterThan(0)
            } else {
                expect(tokensAfter).toBe(-1)
            }
        })
    })
})
