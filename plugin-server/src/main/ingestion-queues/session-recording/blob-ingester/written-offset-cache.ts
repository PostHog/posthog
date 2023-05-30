import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'

import { PluginsServerConfig, RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'

const Keys = {
    offsetHighWaterMark(partition: number): string {
        return `@posthog/replay/partition-high-water-mark/partition-${partition}`
    },
}

/**
 * If a file is written to S3 we need to know the offset of the last message in that file so that we can
 * commit it to Kafka. But we don't write every offset as we bundle files to reduce the number of writes.
 *
 * And not every attempted commit will succeed
 *
 * That means if a consumer restarts or a rebalance moves a partition to another consumer we need to know
 * which offsets have been written to S3 and which haven't so that we don't re-process those messages.
 */
export class WrittenOffsetCache {
    constructor(private redisPool: RedisPool, private serverConfig: PluginsServerConfig) {}

    private async run<T>(description: string, fn: (client: Redis) => Promise<T>): Promise<T | null> {
        const client = await this.redisPool.acquire()
        const timeout = timeoutGuard(`${description} delayed. Waiting over 30 seconds.`)
        try {
            return await fn(client)
        } catch (error) {
            if (error instanceof SyntaxError) {
                // invalid JSON
                return null
            } else {
                throw error
            }
        } finally {
            clearTimeout(timeout)
            await this.redisPool.release(client)
        }
    }

    public async set(partition: number, offset: number): Promise<void> {
        const key = Keys.offsetHighWaterMark(partition)

        try {
            await this.run(`write offset high-water mark ${key} `, async (client) => {
                // there is no TTL on this key, once an offset has been written for a partition it always has been
                // if we stop using this mechanism we can remove this key manually
                return client.hset(key, partition.toString(), offset.toString())
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to add high-water mark for partition', {
                error,
                key,
                partition,
                offset,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    partition,
                },
            })
        }
    }

    public async get(partition: number): Promise<number | null> {
        const key = Keys.offsetHighWaterMark(partition)

        try {
            return await this.run(`read offset high-water mark ${key} `, async (client) => {
                const redisValue = await client.hget(key, partition.toString())
                return redisValue ? parseInt(redisValue) : null
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to read high-water mark for partition', {
                error,
                key,
                partition,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    partition,
                },
            })
            return null
        }
    }
}
