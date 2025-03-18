import { CacheOptions } from '@posthog/plugin-scaffold'
import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'

import { RedisOperationError } from '../../utils/db/error'
import { timeoutGuard } from '../../utils/db/utils'
import { parseJSON } from '../../utils/json-parse'
import { instrumentQuery } from '../../utils/metrics'
import { tryTwice } from '../../utils/utils'

/** The recommended way of accessing the database. */
export class RedisHelpers {
    /** Redis used for various caches. */
    redisPool: GenericPool<Redis.Redis>

    constructor(redisPool: GenericPool<Redis.Redis>) {
        this.redisPool = redisPool
    }

    private instrumentRedisQuery<T>(
        operationName: string,
        tag: string | undefined,
        logContext: Record<string, string | string[] | number>,
        runQuery: (client: Redis.Redis) => Promise<T>
    ): Promise<T> {
        return instrumentQuery(operationName, tag, async () => {
            let client: Redis.Redis
            const timeout = timeoutGuard(`${operationName} delayed. Waiting over 30 sec.`, logContext)
            try {
                client = await this.redisPool.acquire()
            } catch (error) {
                throw new RedisOperationError('Failed to acquire redis client from pool', error, operationName)
            }

            // Don't use a single try/catch/finally for this, as there are 2 potential errors that could be thrown
            // (error and cleanup) and we want to be explicit about which one we choose, rather than relying on
            // "what happens when you throw in a finally block".
            // We explicitly want to throw the error from the operation if there is one, prioritising it over any errors
            // from the cleanup
            let operationResult: { value: T } | { error: Error }
            let cleanupError: Error | undefined

            try {
                operationResult = { value: await runQuery(client) }
            } catch (error) {
                operationResult = { error }
            }

            try {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            } catch (error) {
                cleanupError = error
            }

            if ('error' in operationResult) {
                throw new RedisOperationError(
                    `${operationName} failed for ${JSON.stringify(logContext)}`,
                    operationResult.error,
                    operationName,
                    logContext
                )
            }
            if (cleanupError) {
                throw new RedisOperationError('Failed to release redis client from pool', cleanupError, operationName)
            }
            return operationResult.value
        })
    }

    public redisGet<T = unknown>(
        key: string,
        defaultValue: T,
        tag: string,
        options: CacheOptions = {}
    ): Promise<T | null> {
        const { jsonSerialize = true } = options
        return this.instrumentRedisQuery('query.redisGet', tag, { key }, async (client) => {
            try {
                const value = await tryTwice(
                    async () => await client.get(key),
                    `Waited 5 sec to get redis key: ${key}, retrying once!`
                )
                if (typeof value === 'undefined' || value === null) {
                    return defaultValue
                }
                return value ? (jsonSerialize ? parseJSON(value) : value) : null
            } catch (error) {
                if (error instanceof SyntaxError) {
                    // invalid JSON
                    return null
                } else {
                    throw error
                }
            }
        })
    }

    public redisGetBuffer(key: string, tag: string): Promise<Buffer | null> {
        return this.instrumentRedisQuery('query.redisGetBuffer', tag, { key }, async (client) => {
            return await tryTwice(
                async () => await client.getBuffer(key),
                `Waited 5 sec to get redis key: ${key}, retrying once!`
            )
        })
    }

    public redisSetBuffer(key: string, value: Buffer, tag: string, ttlSeconds?: number): Promise<void> {
        return this.instrumentRedisQuery('query.redisSetBuffer', tag, { key }, async (client) => {
            if (ttlSeconds) {
                await client.setBuffer(key, value, 'EX', ttlSeconds)
            } else {
                await client.setBuffer(key, value)
            }
        })
    }

    public redisSetNX(
        key: string,
        value: unknown,
        tag: string,
        ttlSeconds?: number,
        options: CacheOptions = {}
    ): Promise<'OK' | null> {
        const { jsonSerialize = true } = options

        return this.instrumentRedisQuery('query.redisSetNX', tag, { key }, async (client) => {
            const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
            if (ttlSeconds) {
                return await client.set(key, serializedValue, 'EX', ttlSeconds, 'NX')
            } else {
                return await client.set(key, serializedValue, 'NX')
            }
        })
    }

    public redisSetMulti(kv: Array<[string, unknown]>, ttlSeconds?: number, options: CacheOptions = {}): Promise<void> {
        const { jsonSerialize = true } = options

        return this.instrumentRedisQuery('query.redisSet', undefined, { keys: kv.map((x) => x[0]) }, async (client) => {
            let pipeline = client.multi()
            for (const [key, value] of kv) {
                const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
                if (ttlSeconds) {
                    pipeline = pipeline.set(key, serializedValue, 'EX', ttlSeconds)
                } else {
                    pipeline = pipeline.set(key, serializedValue)
                }
            }
            await pipeline.exec()
        })
    }

    public redisIncr(key: string): Promise<number> {
        return this.instrumentRedisQuery('query.redisIncr', undefined, { key }, async (client) => {
            return await client.incr(key)
        })
    }

    public redisExpire(key: string, ttlSeconds: number): Promise<boolean> {
        return this.instrumentRedisQuery('query.redisExpire', undefined, { key }, async (client) => {
            return (await client.expire(key, ttlSeconds)) === 1
        })
    }

    public redisLPush(key: string, value: unknown, options: CacheOptions = {}): Promise<number> {
        const { jsonSerialize = true } = options

        return this.instrumentRedisQuery('query.redisLPush', undefined, { key }, async (client) => {
            const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string | string[])
            return await client.lpush(key, serializedValue)
        })
    }

    public redisLRange(key: string, startIndex: number, endIndex: number, tag?: string): Promise<string[]> {
        return this.instrumentRedisQuery('query.redisLRange', tag, { key, startIndex, endIndex }, async (client) => {
            return await client.lrange(key, startIndex, endIndex)
        })
    }

    public redisLLen(key: string): Promise<number> {
        return this.instrumentRedisQuery('query.redisLLen', undefined, { key }, async (client) => {
            return await client.llen(key)
        })
    }

    public redisBRPop(key1: string, key2: string): Promise<[string, string]> {
        return this.instrumentRedisQuery('query.redisBRPop', undefined, { key1, key2 }, async (client) => {
            return await client.brpop(key1, key2)
        })
    }

    public redisLRem(key: string, count: number, elementKey: string): Promise<number> {
        return this.instrumentRedisQuery(
            'query.redisLRem',
            undefined,
            {
                key,
                count,
                elementKey,
            },
            async (client) => {
                return await client.lrem(key, count, elementKey)
            }
        )
    }

    public redisLPop(key: string, count: number): Promise<string[]> {
        return this.instrumentRedisQuery(
            'query.redisLPop',
            undefined,
            {
                key,
                count,
            },
            async (client) => {
                return await client.lpop(key, count)
            }
        )
    }

    public redisSAddAndSCard(key: string, value: Redis.ValueType, ttlSeconds?: number): Promise<number> {
        return this.instrumentRedisQuery('query.redisSAddAndSCard', undefined, { key }, async (client) => {
            const multi = client.multi()
            multi.sadd(key, value)
            if (ttlSeconds) {
                multi.expire(key, ttlSeconds)
            }
            multi.scard(key)
            const results = await multi.exec()
            const scardResult = ttlSeconds ? results[2] : results[1]
            return scardResult[1]
        })
    }

    public redisSCard(key: string): Promise<number> {
        return this.instrumentRedisQuery(
            'query.redisSCard',
            undefined,
            {
                key,
            },
            async (client) => {
                return await client.scard(key)
            }
        )
    }

    public redisPublish(channel: string, message: string): Promise<number> {
        return this.instrumentRedisQuery(
            'query.redisPublish',
            undefined,
            {
                channel,
                message,
            },
            async (client) => {
                return await client.publish(channel, message)
            }
        )
    }
}
