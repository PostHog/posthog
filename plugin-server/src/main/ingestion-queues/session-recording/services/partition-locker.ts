import { captureException } from '@sentry/node'
import { randomUUID } from 'crypto'
import { Redis } from 'ioredis'
import { TopicPartition } from 'node-rdkafka-acosom'

import { RedisPool } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'

export const topicPartitionKey = (prefix: string, tp: TopicPartition) => {
    return `${prefix}locks/${tp.topic}/${tp.partition}`
}

const FLAG_EXPIRE_MS = 'PX'

/**
 * Due to the nature of batching, we can't rely solely on Kafka for consumer locking.
 *
 * When a rebalance occurs we try to flush data to S3 so that the new consumer doesn't have to re-process it.
 * To do this we keep a "lock" in place until we have flushed as much data as possible.
 */
export class PartitionLocker {
    consumerID = process.env.HOSTNAME ?? randomUUID()
    delay = 1000
    ttl = 30000

    constructor(private redisPool: RedisPool, private keyPrefix = '@posthog/replay/') {}

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
        // Return a unique set of topicpartition keys
        const keys = new Set<string>()
        tps.forEach((tp) => keys.add(topicPartitionKey(this.keyPrefix, tp)))
        return [...keys]
    }
    /* 
        Claim the lock for partitions for this consumer
        - If already locked, we extend the TTL
        - If it is claimed, we wait and retry until it is cleared 
        - If unclaimed, we claim it
    */
    public async claim(tps: TopicPartition[]) {
        const keys = this.keys(tps)
        const blockingConsumers = new Set(...[this.consumerID])

        try {
            while (blockingConsumers.size !== 0) {
                blockingConsumers.clear()

                await this.run(`claim keys that belong to this consumer`, async (client) => {
                    await Promise.allSettled(
                        keys.map(async (key) => {
                            const existingClaim = await client.get(key)

                            if (existingClaim && existingClaim !== this.consumerID) {
                                // Still claimed by someone else!
                                blockingConsumers.add(existingClaim)
                                return
                            }

                            // Set the key so it is claimed by us
                            const res = await client.set(key, this.consumerID, FLAG_EXPIRE_MS, this.ttl)
                            if (!res) {
                                blockingConsumers.add(this.consumerID)
                            }
                        })
                    )
                })

                if (blockingConsumers.size > 0) {
                    status.warn(
                        '🔒',
                        `PartitionLocker failed to claim keys. Waiting ${this.delay} before retrying...`,
                        {
                            id: this.consumerID,
                            blockingConsumers: [...blockingConsumers],
                        }
                    )
                    await new Promise((r) => setTimeout(r, this.delay))
                }
            }

            status.debug('🔒', 'PartitionLocker claimed all required keys')
        } catch (error) {
            status.error('🧨', 'PartitionLocker errored to claim keys', {
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
            throw error
        }
    }
}
