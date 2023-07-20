import { captureException } from '@sentry/node'
import { Redis } from 'ioredis'
import { TopicPartition } from 'node-rdkafka-acosom'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'

export const offsetHighWaterMarkKey = (prefix: string, tp: TopicPartition) => {
    return `${prefix}/${tp.topic}/${tp.partition}`
}

export type SessionOffsetHighWaterMarks = Record<string, number | undefined>

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
    // Watermarks are held in memory and synced back to redis on commit
    // We don't need to load them more than once per TP as this consumer is the only thing writing to it
    private topicPartitionWaterMarks: Record<string, Promise<SessionOffsetHighWaterMarks> | undefined> = {}

    constructor(private redisPool: RedisPool, private keyPrefix = '@posthog/replay/partition-high-water-marks') {}

    private async run<T>(description: string, fn: (client: Redis) => Promise<T>): Promise<T> {
        const client = await this.redisPool.acquire()
        const timeout = timeoutGuard(`${description} delayed. Waiting over 30 seconds.`)
        try {
            return await fn(client)
        } finally {
            clearTimeout(timeout)
            await this.redisPool.release(client)
        }
    }

    public async getWaterMarks(tp: TopicPartition): Promise<SessionOffsetHighWaterMarks> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, tp)

        // If we already have a watermark promise then we return it (i.e. we don't want to load the watermarks twice)
        if (!this.topicPartitionWaterMarks[key]) {
            this.topicPartitionWaterMarks[key] = this.run(`read all offset high-water mark for ${key} `, (client) =>
                client.zrange(key, 0, -1, 'WITHSCORES')
            ).then((redisValue) => {
                // NOTE: We do this in a secondary promise to release the previous redis client

                // redisValue is an array of [sessionId, offset, sessionId, offset, ...]
                // we want to convert it to an object of { sessionId: offset, sessionId: offset, ... }
                const highWaterMarks = redisValue.reduce(
                    (acc: SessionOffsetHighWaterMarks, value: string, index: number) => {
                        if (index % 2 === 0) {
                            acc[value] = parseInt(redisValue[index + 1])
                        }
                        return acc
                    },
                    {}
                )

                this.topicPartitionWaterMarks[key] = Promise.resolve(highWaterMarks)

                return highWaterMarks
            })
        }

        return this.topicPartitionWaterMarks[key]!
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
            }).then(async () => {
                // NOTE: We do this in a secondary promise to release the previous redis client
                const watermarks = await this.getWaterMarks(tp)
                watermarks[sessionId] = offset
                this.topicPartitionWaterMarks[key] = Promise.resolve(watermarks)
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

    public async onCommit(tp: TopicPartition, offset: number): Promise<void> {
        const key = offsetHighWaterMarkKey(this.keyPrefix, tp)
        try {
            return await this.run(`commit all below offset high-water mark for ${key} `, async (client) => {
                const numberRemoved = await client.zremrangebyscore(key, '-Inf', offset)
                status.info('📝', 'WrittenOffsetCache committed all below high-water mark for partition', {
                    numberRemoved,
                    ...tp,
                    offset,
                })
                const watermarks = await this.getWaterMarks(tp)
                // remove each key in currentHighWaterMarks that has an offset less than or equal to the offset we just committed
                Object.entries(watermarks).forEach(([sessionId, value]) => {
                    if (value && value <= offset) {
                        delete watermarks[sessionId]
                    }
                })

                this.topicPartitionWaterMarks[key] = Promise.resolve(watermarks)
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
        }
    }

    /**
     * if there isn't already a high-water mark for this topic partition
     * then this method calls getAll to get all the high-water marks for this topic partition
     * it assumes that it has the latest high-water marks for this topic partition
     * so that callers are safe to drop messages
     */
    public async isBelowHighWaterMark(tp: TopicPartition, sessionId: string, offset: number): Promise<boolean> {
        const highWaterMarks = await this.getWaterMarks(tp)

        return offset <= (highWaterMarks[sessionId] ?? -1)
    }

    public revoke(tp: TopicPartition) {
        delete this.topicPartitionWaterMarks[offsetHighWaterMarkKey(this.keyPrefix, tp)]
    }
}
