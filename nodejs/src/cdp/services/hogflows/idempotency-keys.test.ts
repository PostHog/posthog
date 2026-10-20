import Redis from 'ioredis'

import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { createRedisClient } from '~/common/utils/db/redis'
import { UUIDT } from '~/common/utils/utils'

import { IdempotencyKeys, createIdempotencyValkeyPool } from './idempotency-keys'

describe('IdempotencyKeys', () => {
    let valkey: RedisV2
    let keys: IdempotencyKeys
    let key: string

    beforeAll(() => {
        valkey = createIdempotencyValkeyPool(defaultConfig)!
        keys = new IdempotencyKeys(valkey, 'test')
    })

    beforeEach(() => {
        // A fresh key per test, so no test reads a key another one left in Valkey.
        key = `key-${new UUIDT().toString()}`
    })

    it('holds a key while the first request queues, then replays its run', async () => {
        expect(await keys.reserve(1, key, 'request-a', 'run-1')).toEqual({ status: 'reserved' })
        expect(await keys.reserve(1, key, 'request-a', 'run-2')).toEqual({ status: 'in_flight' })
        expect(await keys.reserve(1, key, 'request-b', 'run-3')).toEqual({ status: 'conflict' })

        await keys.markQueued(1, key, 'request-a', 'run-1')

        expect(await keys.reserve(1, key, 'request-a', 'run-4')).toEqual({ status: 'replayed', invocationId: 'run-1' })
        expect(await keys.reserve(2, key, 'request-a', 'run-5')).toEqual({ status: 'reserved' })
    })

    it('frees a key only for the request that holds it', async () => {
        await keys.reserve(1, key, 'request-a', 'run-1')

        await keys.release(1, key, 'run-2')
        expect(await keys.reserve(1, key, 'request-a', 'run-3')).toEqual({ status: 'in_flight' })

        await keys.release(1, key, 'run-1')
        expect(await keys.reserve(1, key, 'request-a', 'run-4')).toEqual({ status: 'reserved' })
    })

    it('records the run when the queue write outlasts the pending hold', async () => {
        await keys.reserve(1, key, 'request-a', 'run-1')
        // The pending hold expires while the queue write is still running.
        await valkey.useClient({ name: 'test-expire' }, (client) => client.del(keys['redisKey'](1, key)))

        await keys.markQueued(1, key, 'request-a', 'run-1')

        expect(await keys.reserve(1, key, 'request-a', 'run-2')).toEqual({ status: 'replayed', invocationId: 'run-1' })
    })

    it('reports the store as unavailable when it is not configured', async () => {
        expect(await new IdempotencyKeys(null, 'test').reserve(1, key, 'request-a', 'run-1')).toEqual({
            status: 'unavailable',
        })
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
