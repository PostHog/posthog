import * as Sentry from '@sentry/node'
import { Consumer, EachBatchPayload, Kafka, KafkaMessage } from 'kafkajs'

import { Hub, Queue } from '../../../types'
import { status } from '../../../utils/status'
import { groupIntoBatches, killGracefully } from '../../../utils/utils'

export abstract class KafkaQueue implements Queue {
    protected pluginsServer: Hub
    protected kafka: Kafka
    protected consumer: Consumer
    protected wasConsumerRan: boolean
    protected consumerName: string
    protected topic: string

    constructor(pluginsServer: Hub, consumer: Consumer, topic: string, consumerName = '') {
        this.pluginsServer = pluginsServer
        this.kafka = pluginsServer.kafka!
        this.consumer = consumer
        this.wasConsumerRan = false
        this.consumerName = consumerName
        this.topic = topic
    }

    protected abstract eachMessage(message: KafkaMessage): Promise<void>

    protected async eachBatch({
        batch,
        resolveOffset,
        heartbeat,
        commitOffsetsIfNecessary,
        isRunning,
        isStale,
    }: EachBatchPayload): Promise<void> {
        const batchStartTimer = new Date()

        try {
            const messageBatches = groupIntoBatches(
                batch.messages,
                this.pluginsServer.WORKER_CONCURRENCY * this.pluginsServer.TASKS_PER_WORKER
            )

            for (const messageBatch of messageBatches) {
                if (!isRunning() || isStale()) {
                    status.info(
                        '🚪',
                        `${this.consumerName} consumer: Bailing out of a batch of ${batch.messages.length} events`,
                        {
                            isRunning: isRunning(),
                            isStale: isStale(),
                            msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                        }
                    )
                    return
                }

                await Promise.all(messageBatch.map((message) => this.eachMessage(message)))

                // this if should never be false, but who can trust computers these days
                if (messageBatch.length > 0) {
                    resolveOffset(messageBatch[messageBatch.length - 1].offset)
                }
                await commitOffsetsIfNecessary()
                await heartbeat()
            }

            status.info(
                '🧩',
                `${this.consumerName} consumer: Kafka batch of ${batch.messages.length} events completed in ${
                    new Date().valueOf() - batchStartTimer.valueOf()
                }ms`
            )
        } finally {
            this.pluginsServer.statsd?.timing('kafka_queue.each_batch', batchStartTimer, {
                consumerName: this.consumerName,
            })
        }
    }

    async start(): Promise<void> {
        const startPromise = new Promise<void>(async (resolve, reject) => {
            this.consumer.on(this.consumer.events.GROUP_JOIN, () => {
                resolve()
            })
            this.consumer.on(this.consumer.events.CRASH, ({ payload: { error } }) => reject(error))
            status.info('⏬', `Connecting Kafka consumer ${this.consumerName} to ${this.pluginsServer.KAFKA_HOSTS}...`)
            this.wasConsumerRan = true

            await this.consumer.subscribe({
                topic: this.topic,
            })

            // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
            await this.consumer.run({
                eachBatchAutoResolve: false,
                autoCommitInterval: 1000, // autocommit every 1000 ms…
                autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
                partitionsConsumedConcurrently: this.pluginsServer.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
                eachBatch: async (payload) => {
                    try {
                        await this.eachBatch(payload)
                    } catch (error) {
                        const eventCount = payload.batch.messages.length
                        this.pluginsServer.statsd?.increment('kafka_queue_each_batch_failed_events', eventCount, {
                            consumerName: this.consumerName,
                        })
                        status.info('💀', `${this.consumerName} consumer: Kafka batch of ${eventCount} events failed!`)
                        if (error.type === 'UNKNOWN_MEMBER_ID') {
                            status.info(
                                '💀',
                                `${this.consumerName} consumer: Probably the batch took longer than the session and we couldn't commit the offset`
                            )
                        }
                        if (
                            error.message &&
                            !error.message.includes('The group is rebalancing, so a rejoin is needed') &&
                            !error.message.includes('Specified group generation id is not valid')
                        ) {
                            Sentry.captureException(error)
                        }
                        throw error
                    }
                },
            })
        })
        return await startPromise
    }

    async pause(): Promise<void> {
        if (this.wasConsumerRan && !this.isPaused()) {
            status.info('⏳', `Pausing Kafka consumer ${this.consumerName}...`)
            this.consumer.pause([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
            status.info('⏸', `Kafka consumer ${this.consumerName} paused!`)
        }
        return Promise.resolve()
    }

    resume(): void {
        if (this.wasConsumerRan && this.isPaused()) {
            status.info('⏳', `Resuming Kafka consumer ${this.consumerName}...`)
            this.consumer.resume([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
            status.info('▶️', `Kafka consumer ${this.consumerName} resumed!`)
        }
    }

    isPaused(): boolean {
        return this.consumer.paused().some(({ topic }) => topic === this.pluginsServer.KAFKA_CONSUMPTION_TOPIC)
    }

    async stop(): Promise<void> {
        status.info('⏳', 'Stopping Kafka queue...')
        try {
            await this.consumer.stop()
            status.info('⏹', `Kafka consumer ${this.consumerName} stopped!`)
        } catch (error) {
            status.error('⚠️', `An error occurred while stopping Kafka consumer ${this.consumerName}:\n`, error)
        }
        try {
            await this.consumer.disconnect()
        } catch {}
    }

    protected static buildConsumer(kafka: Kafka, consumerName: string, groupId?: string): Consumer {
        const consumer = kafka.consumer({
            groupId: groupId ?? 'clickhouse-ingestion',
            readUncommitted: false,
        })
        const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT } = consumer.events
        consumer.on(GROUP_JOIN, ({ payload: { groupId } }) => {
            status.info('✅', `Kafka consumer ${consumerName} joined group ${groupId}!`)
        })
        consumer.on(CRASH, ({ payload: { error, groupId } }) => {
            status.error('⚠️', `Kafka consumer ${consumerName} group ${groupId} crashed:\n`, error)
            Sentry.captureException(error)
            killGracefully()
        })
        consumer.on(CONNECT, () => {
            status.info('✅', `Kafka consumer ${consumerName} connected!`)
        })
        consumer.on(DISCONNECT, () => {
            status.info('🛑', `Kafka consumer ${consumerName} disconnected!`)
        })
        return consumer
    }
}
