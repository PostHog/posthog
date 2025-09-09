// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema
import { createPool } from 'generic-pool'
import { Pipeline, Redis } from 'ioredis'

import { PluginsServerConfig } from '../types'
import { createRedisClient } from '../utils/db/redis'
import { timeoutGuard } from '../utils/db/utils'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'

type WithCheckRateLimit<T> = {
    checkRateLimit: (key: string, now: number, cost: number, poolMax: number, fillRate: number, expiry: number) => T
}

export type CdpRedisClientPipeline = Pipeline & WithCheckRateLimit<number>

export type CdpRedisClient = Omit<Redis, 'pipeline'> &
    WithCheckRateLimit<Promise<number>> & {
        pipeline: () => CdpRedisClientPipeline
    }

export type CdpRedisOptions = {
    name: string
    timeout?: number
    failOpen?: boolean
}

export type CdpRedis = {
    useClient: <T>(options: CdpRedisOptions, callback: (client: CdpRedisClient) => Promise<T>) => Promise<T | null>
    usePipeline: (
        options: CdpRedisOptions,
        callback: (pipeline: CdpRedisClientPipeline) => void
    ) => Promise<Array<[Error | null, any]> | null>
}

// NOTE: We ideally would have this in a file but the current build step doesn't handle anything other than .ts files
const LUA_TOKEN_BUCKET = `
local key = KEYS[1]
local now = ARGV[1]
local cost = ARGV[2]
local poolMax = ARGV[3]
local fillRate = ARGV[4]
local expiry = ARGV[5]
local before = redis.call('hget', key, 'ts')

-- If we don't have a timestamp then we set it to now and fill up the bucket
if before == false then
  local ret = poolMax - cost
  redis.call('hset', key, 'ts', now)
  redis.call('hset', key, 'pool', ret)
  redis.call('expire', key, expiry)
  return ret
end

-- We update the timestamp if it has changed
local timeDiffSeconds = now - before

if timeDiffSeconds > 0 then
  redis.call('hset', key, 'ts', now)
else
  timeDiffSeconds = 0
end

-- Calculate how much should be refilled in the bucket and add it
local owedTokens = timeDiffSeconds * fillRate
local currentTokens = redis.call('hget', key, 'pool')

if currentTokens == false then
  currentTokens = poolMax
end

currentTokens = math.min(currentTokens + owedTokens, poolMax)

-- Remove the cost and return the new number of tokens
if currentTokens - cost >= 0 then
  currentTokens = currentTokens - cost
else
  currentTokens = -1
end

redis.call('hset', key, 'pool', currentTokens)
redis.call('expire', key, expiry)

-- Finally return the value - if it's negative then we've hit the limit
return currentTokens
`

export const createCdpRedisPool = (config: PluginsServerConfig): CdpRedis => {
    const pool = createPool<CdpRedisClient>(
        {
            create: async () => {
                const client = await createRedisClient(config.CDP_REDIS_HOST, {
                    port: config.CDP_REDIS_PORT,
                    password: config.CDP_REDIS_PASSWORD,
                })

                client.defineCommand('checkRateLimit', {
                    numberOfKeys: 1,
                    lua: LUA_TOKEN_BUCKET,
                })

                return client as CdpRedisClient
            },
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.REDIS_POOL_MIN_SIZE,
            max: config.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )

    const useClient: CdpRedis['useClient'] = async (options, callback) => {
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

    const usePipeline: CdpRedis['usePipeline'] = async (options, callback) => {
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
