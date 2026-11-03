import Redis from 'ioredis'
import { register } from 'prom-client'
import { setTimeout as delay } from 'timers/promises'

import { defaultConfig } from '~/common/config/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import * as redisDb from '~/common/utils/db/redis'
import { createRedisClient } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { UUIDT } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'

import { IdempotencyKeys, createIdempotencyValkeyPool } from './idempotency-keys'

const HOUR_MS = 60 * 60 * 1000

describe('IdempotencyKeys', () => {
    // Alerts read this counter, so an outcome that stops being counted silences them.
    const operations = async (scope: string, operation: string, outcome: string): Promise<number> =>
        (await register.getSingleMetric('cdp_hogflow_idempotency_operations_total')!.get()).values.find(
            (v) => v.labels.scope === scope && v.labels.operation === operation && v.labels.outcome === outcome
        )?.value ?? 0

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
        const replayedBefore = await operations('test', 'reserve', 'replayed')
        expect(await keys.reserve(1, key, 'request-a', 'run-1')).toEqual({ status: 'reserved' })
        expect(await keys.reserve(1, key, 'request-a', 'run-2')).toEqual({ status: 'in_flight' })
        expect(await keys.reserve(1, key, 'request-b', 'run-3')).toEqual({ status: 'conflict' })

        await keys.markQueued(1, key, 'request-a', 'run-1')

        expect(await keys.reserve(1, key, 'request-a', 'run-4')).toEqual({ status: 'replayed', invocationId: 'run-1' })
        expect(await keys.reserve(2, key, 'request-a', 'run-5')).toEqual({ status: 'reserved' })
        expect(await operations('test', 'reserve', 'replayed')).toEqual(replayedBefore + 1)
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

    it('records the run once the store recovers from an outage that outlasts the inline attempts', async () => {
        await keys.reserve(1, key, 'request-a', 'run-1')
        const failedBefore = await operations('test', 'mark_queued', 'failed')
        const useClient = valkey.useClient
        const outage = jest.spyOn(valkey, 'useClient').mockRejectedValue(new Error('connection lost'))
        try {
            await keys.markQueued(1, key, 'request-a', 'run-1')
            expect(await operations('test', 'mark_queued', 'failed')).toEqual(failedBefore + 1)
            const inlineAttempts = outage.mock.calls.length
            await waitForExpect(() => expect(outage.mock.calls.length).toBeGreaterThan(inlineAttempts))
            outage.mockImplementation(useClient)

            await waitForExpect(async () =>
                expect(await keys.reserve(1, key, 'request-a', 'run-2')).toEqual({
                    status: 'replayed',
                    invocationId: 'run-1',
                })
            )
        } finally {
            outage.mockRestore()
        }
    })

    it('keeps the replay window of the run when the store recovers hours later', async () => {
        await keys.reserve(1, key, 'request-a', 'run-1')
        const useClient = valkey.useClient
        const outage = jest.spyOn(valkey, 'useClient').mockRejectedValue(new Error('connection lost'))
        const realNow = Date.now
        const clock = jest.spyOn(Date, 'now')
        try {
            await keys.markQueued(1, key, 'request-a', 'run-1')
            clock.mockImplementation(() => realNow() + 12 * HOUR_MS)
            outage.mockImplementation(useClient)

            await waitForExpect(async () =>
                expect(await keys.reserve(1, key, 'request-a', 'run-2')).toEqual({
                    status: 'replayed',
                    invocationId: 'run-1',
                })
            )
            const ttlSeconds = await valkey.useClient({ name: 'test-ttl' }, (client) =>
                client.ttl(keys['redisKey'](1, key))
            )
            expect(ttlSeconds).toBeGreaterThan((12 * HOUR_MS) / 1000 - 60)
            expect(ttlSeconds).toBeLessThanOrEqual((12 * HOUR_MS) / 1000)
        } finally {
            outage.mockRestore()
            clock.mockRestore()
        }
    })

    it('records a retry whose completion fails while the earlier completion of its key is still writing', async () => {
        await keys.reserve(1, key, 'request-a', 'run-1')
        const useClient = valkey.useClient
        const connectionLost = new Error('connection lost')
        let endSlowWrite!: () => void
        const slowWrite = new Promise<void>((resolve) => (endSlowWrite = resolve))
        const store = jest
            .spyOn(valkey, 'useClient')
            .mockRejectedValueOnce(connectionLost)
            .mockRejectedValueOnce(connectionLost)
            .mockImplementationOnce(async (...args) => {
                await slowWrite
                return useClient(...args)
            })
            .mockImplementationOnce(useClient)
            .mockImplementationOnce(useClient)
            .mockRejectedValueOnce(connectionLost)
            .mockRejectedValueOnce(connectionLost)
            .mockImplementation(useClient)
        try {
            await keys.markQueued(1, key, 'request-a', 'run-1')
            await waitForExpect(() => expect(store.mock.calls.length).toEqual(3))
            // The pending hold of run-1 expires, and a retry of the request reserves the key again.
            await valkey.useClient({ name: 'test-expire' }, (client) => client.del(keys['redisKey'](1, key)))
            expect(await keys.reserve(1, key, 'request-a', 'run-2')).toEqual({ status: 'reserved' })
            await keys.markQueued(1, key, 'request-a', 'run-2')
            endSlowWrite()

            await waitForExpect(async () =>
                expect(await keys.reserve(1, key, 'request-a', 'run-3')).toEqual({
                    status: 'replayed',
                    invocationId: 'run-2',
                })
            )
        } finally {
            store.mockRestore()
        }
    })

    it('records the reserved run when a retry that queued without a reservation also fails to complete', async () => {
        expect(await keys.reserve(1, key, 'request-a', 'run-1')).toEqual({ status: 'reserved' })
        const useClient = valkey.useClient
        const outage = jest.spyOn(valkey, 'useClient').mockRejectedValue(new Error('connection lost'))
        try {
            await keys.markQueued(1, key, 'request-a', 'run-1')
            // The webhook route queues a retry without a reservation when the store is unavailable.
            expect(await keys.reserve(1, key, 'request-a', 'run-2')).toEqual({ status: 'unavailable' })
            await keys.markQueued(1, key, 'request-a', 'run-2')
            // The store recovers before the pending hold of run-1 expires.
            outage.mockImplementation(useClient)

            await waitForExpect(async () =>
                expect(await keys.reserve(1, key, 'request-a', 'run-3')).toEqual({
                    status: 'replayed',
                    invocationId: 'run-1',
                })
            )
        } finally {
            outage.mockRestore()
        }
    })

    it('sends one store call at a time while failed completions wait for the store', async () => {
        let inFlight = 0
        let maxInFlight = 0
        const outage = jest.spyOn(valkey, 'useClient').mockImplementation(async () => {
            inFlight++
            maxInFlight = Math.max(maxInFlight, inFlight)
            await delay(50)
            inFlight--
            throw new Error('connection lost')
        })
        try {
            await Promise.all(
                Array.from({ length: 20 }, (_, i) => keys.markQueued(1, `${key}-${i}`, 'request-a', `run-${i}`))
            )
            maxInFlight = 0
            const inlineAttempts = outage.mock.calls.length
            await waitForExpect(() => expect(outage.mock.calls.length).toBeGreaterThanOrEqual(inlineAttempts + 2))

            expect(maxInFlight).toEqual(1)
        } finally {
            outage.mockRestore()
        }
    })

    it('reports the store as unavailable when it is not configured', async () => {
        const unavailableBefore = await operations('unconfigured', 'reserve', 'unavailable')

        expect(await new IdempotencyKeys(null, 'unconfigured').reserve(1, key, 'request-a', 'run-1')).toEqual({
            status: 'unavailable',
        })
        expect(await operations('unconfigured', 'reserve', 'unavailable')).toEqual(unavailableBefore + 1)
    })

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
        expect(IdempotencyKeys.fingerprint(first) === IdempotencyKeys.fingerprint(second)).toBe(same)
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
