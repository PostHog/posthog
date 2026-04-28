import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { DMAT_KILL_SWITCH_REDIS_KEY, DmatKillSwitch } from './dmat-kill-switch'

function fakeRedisPool(getResults: (string | null)[]): {
    pool: GenericPool<Redis>
    redisClient: { get: jest.Mock }
} {
    let callIndex = 0
    const redisClient = {
        get: jest.fn().mockImplementation(() => {
            const result = getResults[Math.min(callIndex, getResults.length - 1)]
            callIndex += 1
            return Promise.resolve(result)
        }),
    }

    const pool = {
        acquire: jest.fn().mockResolvedValue(redisClient),
        release: jest.fn().mockResolvedValue(undefined),
    } as unknown as GenericPool<Redis>

    return { pool, redisClient }
}

describe('DmatKillSwitch', () => {
    it('defaults to enabled (isDisabled() === false) when Redis key is absent', async () => {
        const { pool, redisClient } = fakeRedisPool([null])
        const killSwitch = new DmatKillSwitch(pool)
        await killSwitch.forceRefresh()

        expect(killSwitch.isDisabled()).toBe(false)
        expect(redisClient.get).toHaveBeenCalledWith(DMAT_KILL_SWITCH_REDIS_KEY)
    })

    it('reports disabled when Redis key is set to any non-empty value', async () => {
        const { pool } = fakeRedisPool(['1'])
        const killSwitch = new DmatKillSwitch(pool)
        await killSwitch.forceRefresh()

        expect(killSwitch.isDisabled()).toBe(true)
    })

    it('treats empty string as enabled (so accidentally-cleared keys do not kill ingestion)', async () => {
        const { pool } = fakeRedisPool([''])
        const killSwitch = new DmatKillSwitch(pool)
        await killSwitch.forceRefresh()

        expect(killSwitch.isDisabled()).toBe(false)
    })

    it('reflects flips between calls — once Redis says enabled, isDisabled() goes back to false', async () => {
        const { pool } = fakeRedisPool(['1', null])
        const killSwitch = new DmatKillSwitch(pool)

        await killSwitch.forceRefresh()
        expect(killSwitch.isDisabled()).toBe(true)

        await killSwitch.forceRefresh()
        expect(killSwitch.isDisabled()).toBe(false)
    })

    it('returns enabled (false) before the first refresh completes', () => {
        const { pool } = fakeRedisPool(['1'])
        const killSwitch = new DmatKillSwitch(pool)

        // No await of forceRefresh — the cache is empty, tryGet() returns undefined,
        // isDisabled() must return false rather than throw or block the hot path.
        expect(killSwitch.isDisabled()).toBe(false)
    })
})
