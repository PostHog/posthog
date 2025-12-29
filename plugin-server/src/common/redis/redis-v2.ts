import { createPool } from 'generic-pool'
import { Pipeline, Redis } from 'ioredis'

import { RedisPoolConfig, createRedisFromConfig } from '../../utils/db/redis'
import { timeoutGuard } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { defineLuaTokenBucket } from './redis-token-bucket.lua'

type WithCheckRateLimit<T, TV2> = {
    checkRateLimit: (key: string, now: number, cost: number, poolMax: number, fillRate: number, expiry: number) => T
    checkRateLimitV2: (key: string, now: number, cost: number, poolMax: number, fillRate: number, expiry: number) => TV2
}

export type RedisClientPipeline = Pipeline & WithCheckRateLimit<number, [number, number]>

export type RedisClient = Omit<Redis, 'pipeline'> &
    WithCheckRateLimit<Promise<number>, Promise<[number, number]>> & {
        pipeline: () => RedisClientPipeline
    }

export type RedisOptions = {
    name: string
    timeout?: number
    failOpen?: boolean
}

export type RedisV2 = {
    useClient: <T>(options: RedisOptions, callback: (client: RedisClient) => Promise<T>) => Promise<T | null>
    usePipeline: (
        options: RedisOptions,
        callback: (pipeline: RedisClientPipeline) => void
    ) => Promise<Array<[Error | null, any]> | null>
}

export const createRedisV2PoolFromConfig = (config: RedisPoolConfig): RedisV2 => {
    const pool = createPool<RedisClient>(
        {
            create: async () => {
                const client = await createRedisFromConfig(config.connection)

                defineLuaTokenBucket(client)

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
        }
    )

    const useClient: RedisV2['useClient'] = async (options, callback) => {
        const timeout = timeoutGuard(
            `Redis call ${options.name} delayed. Waiting over 30 seconds.`,
            undefined,
            options.timeout
        )
        const client = await pool.acquire()

        try {
            return await callback(client)
        } catch (e) {
            if (options.failOpen) {
                // We log the error and return null
                captureException(e)
                logger.error(`Redis call${options.name} failed`, e)
                return null
            }
            throw e
        } finally {
            await pool.release(client)
            clearTimeout(timeout)
        }
    }

    const usePipeline: RedisV2['usePipeline'] = async (options, callback) => {
        return useClient(options, async (client) => {
            const pipeline = client.pipeline()
            callback(pipeline)
            return pipeline.exec()
        })
    }

    return {
        useClient,
        usePipeline,
    }
}

export type RedisPipelineResults = [Error | null, any][]

export const getRedisPipelineResults = (
    res: RedisPipelineResults,
    index: number,
    numOperations: number
): RedisPipelineResults => {
    // pipeline results are just a big array of operation results so we need to slice out the correct parts
    return res.slice(index * numOperations, index * numOperations + numOperations)
}
