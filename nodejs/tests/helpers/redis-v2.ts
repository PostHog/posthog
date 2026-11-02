import { Pool, createPool } from 'generic-pool'

import { defineLuaTokenBucketV2 } from '~/common/redis/redis-token-bucket-v2.lua'
import { defineLuaTokenBucketV3 } from '~/common/redis/redis-token-bucket-v3.lua'
import { RedisClient, RedisOptions, RedisV2 } from '~/common/redis/redis-v2'
import { RedisPoolConfig, createRedisFromConfig } from '~/common/utils/db/redis'

export class TestRedisV2 implements RedisV2 {
    private readonly pool: Pool<RedisClient>

    constructor(config: RedisPoolConfig) {
        this.pool = createPool<RedisClient>(
            {
                create: async () => {
                    const client = await createRedisFromConfig(config.connection)
                    defineLuaTokenBucketV2(client)
                    defineLuaTokenBucketV3(client)
                    return client as RedisClient
                },
                destroy: async (client) => {
                    await client.quit()
                },
            },
            {
                min: config.poolMinSize,
                max: config.poolMaxSize,
                autostart: true,
                acquireTimeoutMillis: config.acquireTimeoutMillis,
            }
        )
    }

    async useClient<T>(options: RedisOptions, callback: (client: RedisClient) => Promise<T>): Promise<T | null> {
        const client = await this.pool.acquire()
        try {
            return await callback(client)
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
