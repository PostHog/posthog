import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'

const offsetHighWaterMarkKey = (sessionId: string) => `@posthog/replay/partition-high-water-marks/${sessionId}`

/**
 * If a file is written to S3 we need to know the offset of the last message in that file so that we can
 * commit it to Kafka. But we don't write every offset as we bundle files to reduce the number of writes.
 *
 * And not every attempted commit will succeed
 *
 * That means if a consumer restarts or a rebalance moves a partition to another consumer we need to know
 * which offsets have been written to S3 for each session, and which haven't
 * so that we don't re-process those messages.
 */
export class WrittenOffsetCache {
    constructor(private redisPool: RedisPool) {}

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

    public async set(sessionId: string, offset: number): Promise<void> {
        const key = offsetHighWaterMarkKey(sessionId)
        try {
            await this.run(`write offset high-water mark ${key} `, async (client) => {
                const pipeline = client.pipeline()
                pipeline.set(key, offset)
                // expire after 7 days
                // if we can't process a session in 7 days we have bigger problems
                // than re-processing some files
                pipeline.expire(key, 7 * 24 * 60 * 60)
                return pipeline.exec()
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to add high-water mark for partition', {
                error,
                key,
                sessionId,
                offset,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    sessionId,
                },
            })
        }
    }

    public async get(sessionId: string): Promise<number | null> {
        const key = offsetHighWaterMarkKey(sessionId)
        try {
            return await this.run(`read offset high-water mark ${key} `, async (client) => {
                const redisValue = await client.get(key)
                return redisValue ? parseInt(redisValue) : null
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to read high-water mark for partition', {
                error,
                key,
                sessionId,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    sessionId,
                },
            })
            return null
        }
    }
}
