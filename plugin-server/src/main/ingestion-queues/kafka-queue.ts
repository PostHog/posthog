import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { Consumer, EachBatchPayload, Kafka, KafkaMessage } from 'kafkajs'

import { Hub, Queue, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { groupIntoBatches, killGracefully, sanitizeEvent } from '../../utils/utils'
import { runInstrumentedFunction } from '../utils'
import { KAFKA_BUFFER, KAFKA_EVENTS_JSON } from './../../config/kafka-topics'
import { eachBatchBuffer } from './batch-processing/buffer'
import { eachBatchIngestion, ingestEvent } from './batch-processing/ingest-event'

type ConsumerManagementPayload = {
    topic: string
    partitions?: number[] | undefined
}

type EachBatchFunction = (payload: EachBatchPayload, queue: KafkaQueue) => Promise<void>
export class KafkaQueue implements Queue {
    public pluginsServer: Hub
    public workerMethods: WorkerMethods
    private kafka: Kafka
    private consumer: Consumer
    private wasConsumerRan: boolean
    private sleepTimeout: NodeJS.Timeout | null
    private ingestionTopic: string
    private bufferTopic: string
    private asyncHandlersTopic: string
    private eachBatch: Record<string, EachBatchFunction>

    constructor(pluginsServer: Hub, workerMethods: WorkerMethods) {
        this.pluginsServer = pluginsServer
        this.kafka = pluginsServer.kafka!
        this.consumer = KafkaQueue.buildConsumer(this.kafka)
        this.wasConsumerRan = false
        this.workerMethods = workerMethods
        this.sleepTimeout = null

        this.ingestionTopic = this.pluginsServer.KAFKA_CONSUMPTION_TOPIC!
        this.bufferTopic = KAFKA_BUFFER
        this.asyncHandlersTopic = KAFKA_EVENTS_JSON
        this.eachBatch = {
            [this.ingestionTopic]: eachBatchIngestion,
            [this.bufferTopic]: eachBatchBuffer,
            // [this.asyncHandlersTopic]: eachBatchAsyncHandlers
        }
    }

    async start(): Promise<void> {
        const startPromise = new Promise<void>(async (resolve, reject) => {
            this.consumer.on(this.consumer.events.GROUP_JOIN, () => {
                resolve()
            })
            this.consumer.on(this.consumer.events.CRASH, ({ payload: { error } }) => reject(error))
            status.info('⏬', `Connecting Kafka consumer to ${this.pluginsServer.KAFKA_HOSTS}...`)
            this.wasConsumerRan = true

            for (const topic of Object.keys(this.eachBatch)) {
                await this.consumer.subscribe({ topic })
            }

            // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
            await this.consumer.run({
                eachBatchAutoResolve: false,
                autoCommitInterval: 1000, // autocommit every 1000 ms…
                autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
                partitionsConsumedConcurrently: this.pluginsServer.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
                eachBatch: async (payload) => {
                    const topic = payload.batch.topic
                    try {
                        await this.eachBatch[topic](payload, this)
                    } catch (error) {
                        const eventCount = payload.batch.messages.length
                        this.pluginsServer.statsd?.increment('kafka_queue_each_batch_failed_events', eventCount, {
                            topic: topic,
                        })
                        status.info('💀', `Kafka batch of ${eventCount} events for topic ${topic} failed!`)
                        if (error.type === 'UNKNOWN_MEMBER_ID') {
                            status.info(
                                '💀',
                                "Probably the batch took longer than the session and we couldn't commit the offset"
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

    async pause(targetTopic: string = this.pluginsServer.KAFKA_CONSUMPTION_TOPIC!, partition?: number): Promise<void> {
        if (this.wasConsumerRan && !this.isPaused(targetTopic, partition)) {
            const pausePayload: ConsumerManagementPayload = { topic: targetTopic }
            let partitionInfo = ''
            if (partition) {
                pausePayload.partitions = [partition]
                partitionInfo = `(partition ${partition})`
            }

            status.info('⏳', `Pausing Kafka consumer for topic ${targetTopic} ${partitionInfo}...`)
            this.consumer.pause([pausePayload])
            status.info('⏸', `Kafka consumer for topic ${targetTopic} ${partitionInfo} paused!`)
        }
        return Promise.resolve()
    }

    async sleep(sleepMs: number, partition: number, topic = this.bufferTopic): Promise<void> {
        this.sleepTimeout = setTimeout(() => {
            if (this.sleepTimeout) {
                clearTimeout(this.sleepTimeout)
            }
            this.resume(topic, partition)
        }, sleepMs)

        await this.pause(topic, partition)
    }

    resume(targetTopic: string = this.ingestionTopic, partition?: number): void {
        if (this.wasConsumerRan && this.isPaused(targetTopic, partition)) {
            const resumePayload: ConsumerManagementPayload = { topic: targetTopic }
            let partitionInfo = ''
            if (partition) {
                resumePayload.partitions = [partition]
                partitionInfo = `(partition ${partition})`
            }
            status.info('⏳', `Resuming Kafka consumer for topic ${targetTopic} ${partitionInfo}...`)
            this.consumer.resume([resumePayload])
            status.info('▶️', `Kafka consumer for topic ${targetTopic} ${partitionInfo} resumed!`)
        }
    }

    isPaused(targetTopic: string = this.ingestionTopic, partition?: number): boolean {
        // if we pass a partition, check that as well, else just return if the topic is paused
        return this.consumer
            .paused()
            .some(({ topic, partitions }) => topic === targetTopic && (!partition || partitions.includes(partition)))
    }

    async stop(): Promise<void> {
        status.info('⏳', 'Stopping Kafka queue...')
        try {
            await this.consumer.stop()
            status.info('⏹', 'Kafka consumer stopped!')
        } catch (error) {
            status.error('⚠️', 'An error occurred while stopping Kafka queue:\n', error)
        }
        try {
            await this.consumer.disconnect()
        } catch {}
    }

    private static buildConsumer(kafka: Kafka, groupId?: string): Consumer {
        const consumer = kafka.consumer({
            // NOTE: This should never clash with the group ID specified for the kafka engine posthog/ee/clickhouse/sql/clickhouse.py
            groupId: groupId ?? 'clickhouse-ingestion',
            readUncommitted: false,
        })
        const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT } = consumer.events
        consumer.on(GROUP_JOIN, ({ payload: { groupId } }) => {
            status.info('✅', `Kafka consumer joined group ${groupId}!`)
        })
        consumer.on(CRASH, ({ payload: { error, groupId } }) => {
            status.error('⚠️', `Kafka consumer group ${groupId} crashed:\n`, error)
            Sentry.captureException(error)
            killGracefully()
        })
        consumer.on(CONNECT, () => {
            status.info('✅', 'Kafka consumer connected!')
        })
        consumer.on(DISCONNECT, () => {
            status.info('🛑', 'Kafka consumer disconnected!')
        })
        return consumer
    }
}
