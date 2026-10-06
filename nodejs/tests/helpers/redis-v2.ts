import { RedisClient, RedisOptions, RedisV2 } from '~/common/redis/redis-v2'
import { RedisPoolConfig, createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { RedisPool } from '~/types'

export class TestRedisV2 implements RedisV2 {
    private readonly pool: RedisPool

    constructor(config: RedisPoolConfig) {
        this.pool = createRedisPoolFromConfig(config)
    }

    async useClient<T>(options: RedisOptions, callback: (client: RedisClient) => Promise<T>): Promise<T | null> {
        const client = await this.pool.acquire()
        try {
            return await callback(client as RedisClient)
        } catch (error) {
            if (options.failOpen) {
                return null
            }
            throw error
        } finally {
            await this.pool.release(client)
        }
    }

    usePipeline: RedisV2['usePipeline'] = async (options, callback) =>
        this.useClient(options, async (client) => {
            const pipeline = client.pipeline()
            callback(pipeline)
            return await pipeline.exec()
        })

    async close(): Promise<void> {
        await this.pool.drain()
        await this.pool.clear()
    }
}
