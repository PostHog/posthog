import Redis from 'ioredis'

import { defineLuaTokenBucketV2 } from '~/common/redis/redis-token-bucket-v2.lua'
import { defineLuaTokenBucketV3 } from '~/common/redis/redis-token-bucket-v3.lua'
import { RedisClient, RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'
import { TeamManager } from '~/common/utils/team-manager'

import { createExampleInvocation } from '../../_tests/fixtures'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../types'
import { createInvocationResult } from '../../utils/invocation-utils'
import { BASE_REDIS_KEY, HogWatcherConfig, HogWatcherService } from './hog-watcher.service'

const host = process.env.CDP_VALKEY_HOST ?? '127.0.0.1'
const port = Number(process.env.CDP_VALKEY_PORT ?? 6390)

const WATCHER_CONFIG: HogWatcherConfig = {
    hogCostTimingLowerMs: 50,
    hogCostTimingUpperMs: 550,
    hogCostTiming: 100,
    asyncCostTimingLowerMs: 100,
    asyncCostTimingUpperMs: 5000,
    asyncCostTiming: 20,
    sendEvents: false,
    bucketSize: 10000,
    refillRate: 10,
    ttl: 86400,
    automaticallyDisableFunctions: true,
    thresholdDegraded: 0.8,
    stateLockTtl: 60,
    observeResultsBufferTimeMs: 500,
    observeResultsBufferMaxResults: 500,
}

const createResult = (id: string): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    const invocation = createExampleInvocation({ id, team_id: 2 })
    invocation.state.timings = [{ kind: 'hog', duration_ms: 100 }]
    return createInvocationResult(invocation, {}, { finished: true })
}

describe('HogWatcher on Valkey Cluster', () => {
    let valkey: Redis.Redis
    let valkeyPool: RedisV2

    const functionIds = ['valkey-integration-first', 'valkey-integration-second']
    const stateKeys = functionIds.map((id) => `${BASE_REDIS_KEY}/state/${id}`)

    beforeAll(async () => {
        valkey = new Redis(port, host, { maxRetriesPerRequest: 1 })
        defineLuaTokenBucketV2(valkey)
        defineLuaTokenBucketV3(valkey)
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

    it('reproduces CROSSSLOT, then observes the same functions without a multi-key command', async () => {
        const slots = await Promise.all(stateKeys.map((key) => valkey.cluster('keyslot', key)))
        expect(slots[0]).not.toEqual(slots[1])
        await expect(valkey.mget(...stateKeys)).rejects.toThrow('CROSSSLOT')

        const watcher = new HogWatcherService({} as TeamManager, WATCHER_CONFIG, valkeyPool)
        await expect(watcher.observeResults(functionIds.map(createResult))).resolves.toBeUndefined()
    })

    it('allows MGET when keys share a hash tag', async () => {
        await valkey.mset('valkey-test:{same}:first', 'first', 'valkey-test:{same}:second', 'second')
        await expect(valkey.mget('valkey-test:{same}:first', 'valkey-test:{same}:second')).resolves.toEqual([
            'first',
            'second',
        ])
    })
})
