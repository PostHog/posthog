import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'

const offsetHighWaterMarkKey = (prefix: string, topic: string, partition: number) => {
    return `${prefix}/${topic}/${partition}`
}

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
export class SessionOffsetHighWaterMark {
    private topicPartitionWaterMarks: Record<string, Record<string, number>> = {}

    constructor(private redisPool: RedisPool, private keyPrefix = '@posthog/replay/partition-high-water-marks') {}

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

    public async add(topic: string, partition: number, sessionId: string, offset: number): Promise<void> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, topic, partition)
        try {
            await this.run(`write offset high-water mark ${key} `, async (client) => {
                await client.zadd(key, offset, sessionId)
                this.topicPartitionWaterMarks[`${topic}-${partition}`][sessionId] = offset
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to add high-water mark for partition', {
                error: error.message,
                key,
                topic,
                partition,
                sessionId,
                offset,
            })
            captureException(error, {
                extra: {
                    key,
                    offset,
                },
                tags: {
                    topic,
                    partition,
                    sessionId,
                },
            })
        }
    }

    public async getAll(topic: string, partition: number): Promise<Record<string, number> | null> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, topic, partition)
        try {
            return await this.run(`read all offset high-water mark for ${key} `, async (client) => {
                const redisValue = await client.zrange(key, 0, -1, 'WITHSCORES')
                // redisValue is an array of [sessionId, offset, sessionId, offset, ...]
                // we want to convert it to an object of { sessionId: offset, sessionId: offset, ... }
                const highWaterMarks = redisValue.reduce(
                    (acc: Record<string, number>, value: string, index: number) => {
                        if (index % 2 === 0) {
                            acc[value] = parseInt(redisValue[index + 1])
                        }
                        return acc
                    },
                    {}
                )
                if (highWaterMarks) {
                    this.topicPartitionWaterMarks[`${topic}-${partition}`] = highWaterMarks
                }
                return highWaterMarks
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to read high-water marks for partition', {
                error: error.message,
                key,
                topic,
                partition,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    topic,
                    partition,
                },
            })
            return null
        }
    }

    public async onCommit(topic: string, partition: number, offset: number): Promise<Record<string, number> | null> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, topic, partition)
        try {
            return await this.run(`commit all below offset high-water mark for ${key} `, async (client) => {
                const numberRemoved = await client.zremrangebyscore(key, '-Inf', offset)
                console.log('removed ', numberRemoved, ' entries from ', key)
                return await this.getAll(topic, partition)
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to commit high-water mark for partition', {
                error: error.message,
                key,
                topic,
                partition,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    topic,
                    partition,
                },
            })
            return null
        }
    }

    public async isBelowHighWaterMark(
        topic: string,
        partition: number,
        sessionId: string,
        offset: number
    ): Promise<boolean> {
        if (!this.topicPartitionWaterMarks[partition]) {
            const highWaterMarks = await this.getAll(topic, partition)
            if (highWaterMarks) {
                this.topicPartitionWaterMarks[partition] = highWaterMarks
            }
        }
        return offset <= this.topicPartitionWaterMarks[partition]?.[sessionId]
    }
}
