import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'
import { TopicPartition } from 'node-rdkafka-acosom'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'

const offsetHighWaterMarkKey = (prefix: string, tp: TopicPartition) => {
    return `${prefix}/${tp.topic}/${tp.partition}`
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
    private getAllPromise: Promise<Record<string, number> | null> | null = null
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

    public async add(tp: TopicPartition, sessionId: string, offset: number): Promise<void> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, tp)
        try {
            await this.run(`write offset high-water mark ${key} `, async (client) => {
                const returnCountOfUpdatedAndAddedElements = 'CH'
                const updatedCount = await client.zadd(key, returnCountOfUpdatedAndAddedElements, offset, sessionId)
                status.info('📝', 'WrittenOffsetCache added high-water mark for partition', {
                    key,
                    ...tp,
                    sessionId,
                    offset,
                    updatedCount,
                })
                this.topicPartitionWaterMarks[`${tp.topic}-${tp.partition}`][sessionId] = offset
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to add high-water mark for partition', {
                error: error.message,
                key,
                ...tp,
                sessionId,
                offset,
            })
            captureException(error, {
                extra: {
                    key,
                    offset,
                },
                tags: {
                    ...tp,
                    sessionId,
                },
            })
        }
    }

    public async getAll(tp: TopicPartition): Promise<Record<string, number> | null> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, tp)
        try {
            // this might be called multiple times, particularly around rebalances, so, hold one promise for the getAll which multiple callers can await
            if (this.getAllPromise === null) {
                this.getAllPromise = this.run(`read all offset high-water mark for ${key} `, async (client) => {
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

                    this.topicPartitionWaterMarks[`${tp.topic}-${tp.partition}`] = highWaterMarks

                    return highWaterMarks
                })
            }
            return await this.getAllPromise
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to read high-water marks for partition', {
                error: error.message,
                key,
                ...tp,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    ...tp,
                },
            })
            return null
        } finally {
            this.getAllPromise = null
        }
    }

    public async onCommit(tp: TopicPartition, offset: number): Promise<Record<string, number> | null> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, tp)
        try {
            return await this.run(`commit all below offset high-water mark for ${key} `, async (client) => {
                const numberRemoved = await client.zremrangebyscore(key, '-Inf', offset)
                status.info('📝', 'WrittenOffsetCache committed all below high-water mark for partition', {
                    numberRemoved,
                    ...tp,
                    offset,
                })
                return await this.getAll(tp)
            })
        } catch (error) {
            status.error('🧨', 'WrittenOffsetCache failed to commit high-water mark for partition', {
                error: error.message,
                key,
                ...tp,
            })
            captureException(error, {
                extra: {
                    key,
                },
                tags: {
                    ...tp,
                },
            })
            return null
        }
    }

    public async isBelowHighWaterMark(tp: TopicPartition, sessionId: string, offset: number): Promise<boolean> {
        if (!this.topicPartitionWaterMarks[tp.partition]) {
            const highWaterMarks = await this.getAll(tp)
            if (highWaterMarks) {
                this.topicPartitionWaterMarks[tp.partition] = highWaterMarks
            }
        }
        return offset <= this.topicPartitionWaterMarks[tp.partition]?.[sessionId]
    }

    public revoke(tp: TopicPartition) {
        delete this.topicPartitionWaterMarks[`${tp.topic}-${tp.partition}`]
    }
}
