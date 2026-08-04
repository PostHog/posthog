import Redis from 'ioredis'

import { RedisClient, RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'

import { BASE_REDIS_KEY, readValuesAcrossSlots } from './hog-watcher.service'

const host = process.env.CDP_VALKEY_HOST ?? '127.0.0.1'
const port = Number(process.env.CDP_VALKEY_PORT ?? 6390)

describe('Valkey cluster behavior', () => {
    let valkey: Redis.Redis
    let valkeyPool: RedisV2

    const stateKeys = [`${BASE_REDIS_KEY}/state/function-a`, `${BASE_REDIS_KEY}/state/function-b`]

    beforeAll(async () => {
        valkey = new Redis(port, host, { maxRetriesPerRequest: 1 })
        await valkey.ping()
        valkeyPool = {
            useClient: async (_options, callback) => callback(valkey as unknown as RedisClient),
            usePipeline: async (_options, callback) => {
                const pipeline = valkey.pipeline() as RedisClientPipeline
                callback(pipeline)
                return pipeline.exec()
            },
        }
    })

    afterAll(async () => {
        await valkey.quit()
    })

    it('rejects MGET for keys in different slots', async () => {
        await expect(valkey.mget(...stateKeys)).rejects.toThrow('CROSSSLOT')
    })

    it('reads the same cross-slot keys through HogWatcher and preserves ordering', async () => {
        await valkey.set(stateKeys[0], 'first')
        await valkey.set(stateKeys[1], 'second')

        await expect(readValuesAcrossSlots(valkeyPool, [stateKeys[1], stateKeys[0]])).resolves.toEqual([
            'second',
            'first',
        ])
    })

    it('allows MGET when keys share a hash tag', async () => {
        await valkey.mset('valkey-test:{same}:first', 'first', 'valkey-test:{same}:second', 'second')
        await expect(valkey.mget('valkey-test:{same}:first', 'valkey-test:{same}:second')).resolves.toEqual([
            'first',
            'second',
        ])
    })
})
