import * as Sentry from '@sentry/node'
import { Consumer, ConsumerSubscribeTopics, EachBatchPayload, Kafka } from 'kafkajs'

import { Hub, WorkerMethods } from '../../types'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { killGracefully } from '../../utils/utils'
import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from './../../config/kafka-topics'
import { eachBatchAsyncHandlers } from './batch-processing/each-batch-async-handlers'
import { eachBatchIngestion } from './batch-processing/each-batch-ingestion'
import { addMetricsEventListeners, emitConsumerGroupMetrics } from './kafka-metrics'

type ConsumerManagementPayload = {
    topic: string
    partitions?: number[] | undefined
}

type EachBatchFunction = (payload: EachBatchPayload, queue: KafkaQueue) => Promise<void>
export class KafkaQueue {
    public pluginsServer: Hub
    public workerMethods: WorkerMethods
    public consumerReady: boolean
    private kafka: Kafka
    private consumer: Consumer
    private consumerGroupMemberId: string | null
    private wasConsumerRan: boolean
    private ingestionTopic: string
    private eventsTopic: string
    private eachBatch: Record<string, EachBatchFunction>

    constructor(pluginsServer: Hub, workerMethods: WorkerMethods) {
        this.pluginsServer = pluginsServer
        this.kafka = pluginsServer.kafka!
        this.consumer = KafkaQueue.buildConsumer(this.kafka, this.consumerGroupId())
        this.wasConsumerRan = false
        this.workerMethods = workerMethods
        this.consumerGroupMemberId = null
        this.consumerReady = false

        this.ingestionTopic = this.pluginsServer.KAFKA_CONSUMPTION_TOPIC!
        this.eventsTopic = KAFKA_EVENTS_JSON
        this.eachBatch = {
            [this.ingestionTopic]: eachBatchIngestion,
            [this.eventsTopic]: eachBatchAsyncHandlers,
        }
    }

    topics(): ConsumerSubscribeTopics {
        const topics = []

        if (this.pluginsServer.capabilities.ingestion) {
            topics.push(this.ingestionTopic)
        } else if (this.pluginsServer.capabilities.processAsyncHandlers) {
            topics.push(this.eventsTopic)
        } else {
            throw Error('No topics to consume, KafkaQueue should not be started')
        }

        return { topics }
    }

    consumerGroupId(): string {
        if (this.pluginsServer.capabilities.ingestion) {
            return `${KAFKA_PREFIX}clickhouse-ingestion`
        } else if (this.pluginsServer.capabilities.processAsyncHandlers) {
            return `${KAFKA_PREFIX}clickhouse-plugin-server-async`
        } else {
            throw Error('No topics to consume, KafkaQueue should not be started')
        }
    }

    async start(): Promise<void> {
        const timeout = timeoutGuard(
            `Kafka queue is slow to start. Waiting over 1 minute to join the consumer group`,
            {
                topics: this.topics(),
            },
            60000
        )

        const startPromise = new Promise<void>(async (resolve, reject) => {
            addMetricsEventListeners(this.consumer, this.pluginsServer.statsd)

            this.consumer.on(this.consumer.events.GROUP_JOIN, ({ payload }) => {
                status.info('ℹ️', 'Kafka joined consumer group', JSON.stringify(payload))
                this.consumerReady = true
                this.consumerGroupMemberId = payload.memberId
                clearTimeout(timeout)
                resolve()
            })
            this.consumer.on(this.consumer.events.CRASH, ({ payload: { error } }) => reject(error))
            status.info('⏬', `Connecting Kafka consumer to ${this.pluginsServer.KAFKA_HOSTS}...`)
            this.wasConsumerRan = true

            await this.consumer.connect()
            await this.consumer.subscribe(this.topics())

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
                        if (error.message) {
                            let logToSentry = true
                            const messagesToIgnore = {
                                'The group is rebalancing, so a rejoin is needed': 'group_rebalancing',
                                'Specified group generation id is not valid': 'generation_id_invalid',
                                'Could not find person with distinct id': 'person_not_found',
                                'The coordinator is not aware of this member': 'not_aware_of_member',
                            }
                            for (const [msg, metricSuffix] of Object.entries(messagesToIgnore)) {
                                if (error.message.includes(msg)) {
                                    this.pluginsServer.statsd?.increment('each_batch_error_' + metricSuffix)
                                    logToSentry = false
                                }
                            }
                            if (logToSentry) {
                                Sentry.captureException(error)
                            }
                        }
                        throw error
                    }
                },
            })
        })
        return await startPromise
    }

    async pause(targetTopic: string, partition?: number): Promise<void> {
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

    resume(targetTopic: string, partition?: number): void {
        if (this.wasConsumerRan && this.isPaused(targetTopic, partition)) {
            const resumePayload: ConsumerManagementPayload = { topic: targetTopic }
            let partitionInfo = ''
            if (partition) {
                resumePayload.partitions = [partition]
                partitionInfo = `(partition ${partition}) `
            }
            status.info('⏳', `Resuming Kafka consumer for topic ${targetTopic} ${partitionInfo}...`)
            this.consumer.resume([resumePayload])
            status.info('▶️', `Kafka consumer for topic ${targetTopic} ${partitionInfo}resumed!`)
        }
    }

    isPaused(targetTopic: string, partition?: number): boolean {
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

        this.consumerReady = false
    }

    emitConsumerGroupMetrics(): Promise<void> {
        return emitConsumerGroupMetrics(this.consumer, this.consumerGroupMemberId, this.pluginsServer)
    }

    private static buildConsumer(kafka: Kafka, groupId: string): Consumer {
        const consumer = kafka.consumer({
            // NOTE: This should never clash with the group ID specified for the kafka engine posthog/ee/clickhouse/sql/clickhouse.py
            groupId,
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
