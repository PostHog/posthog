import Redis from 'ioredis'

import { RedisClient, RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'

import { teamEmailCapBuckets } from '../messaging/email.service'
import { RateLimiterService } from './rate-limiter.service'

const host = process.env.CDP_VALKEY_HOST ?? '127.0.0.1'
const port = Number(process.env.CDP_VALKEY_PORT ?? 6390)

describe('RateLimiterService on Valkey Cluster', () => {
    let valkey: Redis.Redis
    let valkeyPool: RedisV2

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

    it('pair-claims the team email cap buckets without a cross-slot rejection', async () => {
        // Prove the backing store enforces cluster key-slot rules. Without this, swapping the
        // compose service for a non-cluster Valkey would make the claim below pass vacuously.
        await expect(valkey.mget('rate-limiter-test-key-a', 'rate-limiter-test-key-b')).rejects.toThrow('CROSSSLOT')

        // A fresh team id per run keeps the buckets cold, so a full grant is the only correct
        // outcome. The cluster container keeps data between local runs.
        const teamId = Math.floor(Math.random() * 1_000_000_000)
        const buckets = teamEmailCapBuckets(teamId, 50, 100)
        const limiter = new RateLimiterService(valkeyPool, { name: 'team-email-cluster-test' })

        const claim = await limiter.claimAllOrNothingPair([buckets[0], buckets[1]], 10)
        expect(claim).toEqual({ granted: true, deniedIndex: null })
    })
})
