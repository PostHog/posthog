import { captureException } from '@sentry/node'
import { randomUUID } from 'crypto'
import { Redis } from 'ioredis'
import { TopicPartition } from 'node-rdkafka-acosom'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'

export const topicPartitionKey = (prefix: string, tp: TopicPartition) => {
    return `${prefix}/${tp.topic}/${tp.partition}`
}

/**
 * Due to the nature of batching, we can't rely solely on Kafka for consumer locking.
 *
 * When a rebalance occurs we try to flush data to S3 so that the new consumer doesn't have to re-process it.
 * To do this we keep a "lock" in place until we have flushed as much data as possible.
 */
export class PartitionLocker {
    consumerID = randomUUID()
    delay = 1000

    constructor(private redisPool: RedisPool, private keyPrefix = '@posthog/replay/locks') {}

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

    private keys(tps: TopicPartition[]): string[] {
        return tps.map((tp) => topicPartitionKey(this.keyPrefix, tp))
    }
    /* 
        Claim the lock for partitions for this consumer
        - If already locked, we extend the TTL
        - If it is claimed, we wait and retry until it is cleared 
        - If unclaimed, we claim it
    */
    public async claim(tps: TopicPartition[]) {
        const keys = this.keys(tps)
        const unclaimedKeys = [...keys]

        try {
            while (unclaimedKeys.length > 0) {
                await this.run(`claim keys that belong to this consumer`, async (client) => {
                    await Promise.allSettled(
                        keys.map(async (key) => {
                            const existingClaim = await client.get(key)

                            if (existingClaim && existingClaim !== this.consumerID) {
                                // Still claimed by someone else!
                                return
                            }

                            // Set the key so it is claimed by us
                            const success = await client.set(key, this.consumerID, 'NX', 'EX', 30)

                            if (success) {
                                unclaimedKeys.splice(unclaimedKeys.indexOf(key), 1)
                            }
                        })
                    )
                })

                if (unclaimedKeys.length > 0) {
                    status.warn('🧨', `PartitionLocker failed to claim keys. Waiting ${this.delay} before retrying...`)
                }
            }
        } catch (error) {
            status.error('🧨', 'PartitionLocker failed to claim keys', {
                error: error.message,
                keys,
            })
            captureException(error, {
                extra: {
                    keys,
                },
            })
        }
    }

    /* 
        Release a lock for a partition
        - Clear our claim if it is set to our consumer so that another can claim it
    */
    public async release(tps: TopicPartition[]) {
        const keys = this.keys(tps)
        try {
            await this.run(`release keys that belong to this consumer`, async (client) => {
                await Promise.allSettled(
                    keys.map(async (key) => {
                        const value = await client.get(key)
                        if (value === this.consumerID) {
                            await client.del(key)
                        }
                    })
                )
            })
        } catch (error) {
            status.error('🧨', 'PartitionLocker failed to release keys', {
                error: error.message,
                keys,
            })
            captureException(error, {
                extra: {
                    keys,
                },
            })
        }
    }

    // public async getWaterMarks(tp: TopicPartition): Promise<OffsetHighWaterMarks> {
    //     const key = offsetHighWaterMarkKey(this.keyPrefix, tp)

    //     // If we already have a watermark promise then we return it (i.e. we don't want to load the watermarks twice)
    //     if (!this.topicPartitionWaterMarks[key]) {
    //         this.topicPartitionWaterMarks[key] = this.run(`read all offset high-water mark for ${key} `, (client) =>
    //             client.zrange(key, 0, -1, 'WITHSCORES')
    //         ).then((redisValue) => {
    //             // NOTE: We do this in a secondary promise to release the previous redis client

    //             // redisValue is an array of [key, offset, key, offset, ...]
    //             // we want to convert it to an object of { key: offset, key: offset, ... }
    //             const highWaterMarks = redisValue.reduce((acc: OffsetHighWaterMarks, value: string, index: number) => {
    //                 if (index % 2 === 0) {
    //                     acc[value] = parseInt(redisValue[index + 1])
    //                 }
    //                 return acc
    //             }, {})

    //             this.topicPartitionWaterMarks[key] = Promise.resolve(highWaterMarks)

    //             return highWaterMarks
    //         })
    //     }

    //     return this.topicPartitionWaterMarks[key]!
    // }

    // public async add(tp: TopicPartition, id: string, offset: number): Promise<void> {
    //     const key = offsetHighWaterMarkKey(this.keyPrefix, tp)
    //     const watermarks = await this.getWaterMarks(tp)

    //     if (offset <= (watermarks[id] ?? -1)) {
    //         // SANITY CHECK: We don't want to add an offset that is less than or equal to the current offset
    //         return
    //     }

    //     // Immediately update the value so any subsequent calls to getWaterMarks will get the latest value
    //     watermarks[id] = offset
    //     this.topicPartitionWaterMarks[key] = Promise.resolve(watermarks)

    //     try {
    //         await this.run(`write offset high-water mark ${key} `, async (client) => {
    //             await client.zadd(key, 'GT', offset, id)
    //         })
    //     } catch (error) {
    //         status.error('🧨', 'WrittenOffsetCache failed to add high-water mark for partition', {
    //             error: error.message,
    //             key,
    //             ...tp,
    //             id,
    //             offset,
    //         })
    //         captureException(error, {
    //             extra: {
    //                 key,
    //                 offset,
    //             },
    //             tags: {
    //                 ...tp,
    //                 id,
    //             },
    //         })
    //     }
    // }

    // public async clear(tp: TopicPartition, offset: number): Promise<void> {
    //     const key = offsetHighWaterMarkKey(this.keyPrefix, tp)

    //     const watermarks = await this.getWaterMarks(tp)
    //     let hadDeletion = false
    //     Object.entries(watermarks).forEach(([id, value]) => {
    //         if (value && value <= offset) {
    //             delete watermarks[id]
    //             hadDeletion = true
    //         }
    //     })

    //     if (!hadDeletion) {
    //         return
    //     }

    //     try {
    //         return await this.run(`clear all below offset high-water mark for ${key} `, async (client) => {
    //             await client.zremrangebyscore(key, '-Inf', offset)
    //         })
    //     } catch (error) {
    //         status.error('🧨', 'WrittenOffsetCache failed to commit high-water mark for partition', {
    //             error: error.message,
    //             key,
    //             ...tp,
    //         })
    //         captureException(error, {
    //             extra: {
    //                 key,
    //             },
    //             tags: {
    //                 ...tp,
    //             },
    //         })
    //     }
    // }

    // /**
    //  * if there isn't already a high-water mark for this topic partition
    //  * then this method calls getAll to get all the high-water marks for this topic partition
    //  * it assumes that it has the latest high-water marks for this topic partition
    //  * so that callers are safe to drop messages
    //  */
    // public async isBelowHighWaterMark(tp: TopicPartition, id: string, offset: number): Promise<boolean> {
    //     const highWaterMarks = await this.getWaterMarks(tp)

    //     return offset <= (highWaterMarks[id] ?? -1)
    // }

    // public revoke(tp: TopicPartition) {
    //     delete this.topicPartitionWaterMarks[offsetHighWaterMarkKey(this.keyPrefix, tp)]
    // }
}
