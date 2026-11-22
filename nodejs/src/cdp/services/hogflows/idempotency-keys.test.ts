import Redis from 'ioredis'

import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import * as redisDb from '~/common/utils/db/redis'
import { createRedisClient } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'

import { requestFingerprint } from './idempotency-keys'

describe('idempotency-keys', () => {
    it.each([
        [
            'reordered object keys',
            { a: 1, b: { c: 2, d: [{ e: 3, f: 4 }] } },
            { b: { d: [{ f: 4, e: 3 }], c: 2 }, a: 1 },
            true,
        ],
        ['a changed value', { a: 1 }, { a: 2 }, false],
        ['reordered array items', [1, 2], [2, 1], false],
    ])('fingerprints requests that differ by %s', (_desc, first, second, same) => {
        expect(requestFingerprint(first) === requestFingerprint(second)).toBe(same)
    })

    it('pauses between failed connections and reports no delay after the acquire timeout', async () => {
        jest.useFakeTimers()
        const create = jest.spyOn(redisDb, 'createRedisFromConfig').mockRejectedValue(new Error('WRONGPASS'))
        const warn = jest.spyOn(logger, 'warn')
        try {
            const pool = createRedisV2PoolFromConfig({
                connection: { url: '127.0.0.1', name: 'pause-test', exitOnRepeatedErrors: false },
                poolMinSize: 0,
                poolMaxSize: 1,
                acquireTimeoutMillis: 1500,
            })
            const call = expect(
                pool.useClient({ name: 'test', timeout: 2000 }, (client) => client.ping())
            ).rejects.toThrow()

            await jest.advanceTimersByTimeAsync(1500)
            await call
            // Without the pause, generic-pool retries the failed create thousands of times in this window.
            // Only this pool's attempts count, because the suite's shared pool also creates connections.
            const attempts = create.mock.calls.filter(([connection]) => connection.name === 'pause-test')
            expect(attempts.length).toBeLessThanOrEqual(2)

            await jest.advanceTimersByTimeAsync(2000)
            expect(warn).not.toHaveBeenCalledWith('⌛', expect.stringContaining('delayed'), undefined)
        } finally {
            create.mockRestore()
            warn.mockRestore()
            jest.useRealTimers()
        }
    })

    it('closes the client of an unreachable store instead of reconnecting until the process stops', async () => {
        const disconnect = jest.spyOn(Redis.prototype, 'disconnect')
        try {
            // Nothing listens on port 1. A client left open keeps reconnecting and counts each error.
            await expect(
                createRedisClient('127.0.0.1', { port: 1, commandTimeout: 200 }, 'test', false)
            ).rejects.toThrow()
            expect(disconnect).toHaveBeenCalled()
        } finally {
            disconnect.mockRestore()
        }
    })
})
