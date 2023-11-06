import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { Consumer, EachBatchPayload, Kafka } from 'kafkajs'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { BatchConsumer, startBatchConsumer } from '../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../kafka/config'
import { Hub } from '../../types'
import { KafkaConfig } from '../../utils/db/hub'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { killGracefully } from '../../utils/utils'
import { addMetricsEventListeners, emitConsumerGroupMetrics } from './kafka-metrics'

type ConsumerManagementPayload = {
    topic: string
    partitions?: number[] | undefined
}

type KafkaJSBatchFunction = (payload: EachBatchPayload, queue: KafkaJSIngestionConsumer) => Promise<void>

export class KafkaJSIngestionConsumer {
    public pluginsServer: Hub
    public consumerReady: boolean
    public topic: string
    public consumerGroupId: string
    public eachBatch: KafkaJSBatchFunction
    public consumer: Consumer
    public sessionTimeout: number
    private kafka: Kafka
    private consumerGroupMemberId: string | null
    private wasConsumerRan: boolean

    constructor(pluginsServer: Hub, topic: string, consumerGroupId: string, batchHandler: KafkaJSBatchFunction) {
        this.pluginsServer = pluginsServer
        this.kafka = pluginsServer.kafka!
        this.topic = topic
        this.consumerGroupId = consumerGroupId
        this.sessionTimeout = pluginsServer.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS
        this.consumer = KafkaJSIngestionConsumer.buildConsumer(
            this.kafka,
            consumerGroupId,
            this.pluginsServer.KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS,
            this.sessionTimeout
        )
        this.wasConsumerRan = false

        this.consumerGroupMemberId = null
        this.consumerReady = false

        this.eachBatch = batchHandler
    }

    async start(): Promise<void> {
        const timeout = timeoutGuard(
            `Kafka queue is slow to start. Waiting over 1 minute to join the consumer group`,
            {
                topics: [this.topic],
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
            await this.consumer.subscribe({ topics: [this.topic] })

            // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
            await this.consumer.run({
                eachBatchAutoResolve: false,

                autoCommitInterval: 1000, // autocommit every 1000 ms…
                autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
                partitionsConsumedConcurrently: this.pluginsServer.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
                eachBatch: (payload) => this.eachBatchConsumer(payload),
            })
        })
        return await startPromise
    }

    async eachBatchConsumer(payload: EachBatchPayload): Promise<void> {
        const topic = payload.batch.topic
        await instrumentEachBatchKafkaJS(
            topic,
            (payload) => this.eachBatch(payload, this),
            payload,
            this.pluginsServer.statsd
        )
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

    private static buildConsumer(
        kafka: Kafka,
        groupId: string,
        rebalanceTimeout: number | null,
        sessionTimeout: number
    ): Consumer {
        const consumer = kafka.consumer({
            // NOTE: This should never clash with the group ID specified for the kafka engine posthog/ee/clickhouse/sql/clickhouse.py
            groupId,
            sessionTimeout: sessionTimeout,
            readUncommitted: false,
            rebalanceTimeout: rebalanceTimeout ?? undefined,
        })
        setupEventHandlers(consumer)
        return consumer
    }
}

type EachBatchFunction = (messages: Message[], queue: IngestionConsumer) => Promise<void>

export class IngestionConsumer {
    public pluginsServer: Hub
    public consumerReady: boolean
    public topic: string
    public consumerGroupId: string
    public eachBatch: EachBatchFunction
    public consumer?: BatchConsumer

    constructor(pluginsServer: Hub, topic: string, consumerGroupId: string, batchHandler: EachBatchFunction) {
        this.pluginsServer = pluginsServer
        this.topic = topic
        this.consumerGroupId = consumerGroupId

        this.consumerReady = false

        this.eachBatch = batchHandler
    }

    async start(): Promise<BatchConsumer> {
        this.consumer = await startBatchConsumer({
            batchingTimeoutMs: this.pluginsServer.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            consumerErrorBackoffMs: this.pluginsServer.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            connectionConfig: createRdConnectionConfigFromEnvVars(this.pluginsServer as KafkaConfig),
            topic: this.topic,
            groupId: this.consumerGroupId,
            autoCommit: true,
            sessionTimeout: this.pluginsServer.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
            consumerMaxBytes: this.pluginsServer.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.pluginsServer.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            consumerMaxWaitMs: this.pluginsServer.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            fetchBatchSize: this.pluginsServer.INGESTION_BATCH_SIZE,
            topicCreationTimeoutMs: this.pluginsServer.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            eachBatch: (payload) => this.eachBatchConsumer(payload),
        })
        this.consumerReady = true
        return this.consumer
    }

    async eachBatchConsumer(messages: Message[]): Promise<void> {
        await instrumentEachBatch(
            this.topic,
            (messages) => this.eachBatch(messages, this),
            messages,
            this.pluginsServer.statsd
        )
    }

    async stop(): Promise<void> {
        status.info('⏳', 'Stopping Kafka queue...')
        try {
            await this.consumer?.stop()
            status.info('⏹', 'Kafka consumer stopped!')
        } catch (error) {
            status.error('⚠️', 'An error occurred while stopping Kafka queue:\n', error)
        }

        this.consumerReady = false
    }
}

export const setupEventHandlers = (consumer: Consumer): void => {
    const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT, COMMIT_OFFSETS } = consumer.events
    let offsets: { [key: string]: string } = {} // Keep a record of offsets so we can report on process periodically
    let statusInterval: NodeJS.Timeout
    let groupId: string

    consumer.on(GROUP_JOIN, ({ payload }) => {
        offsets = {}
        groupId = payload.groupId
        status.info('✅', `Kafka consumer joined group ${groupId}!`)
        clearInterval(statusInterval)
        statusInterval = setInterval(() => {
            status.info('ℹ️', 'consumer_status', { groupId, offsets })
        }, 10000)
    })
    consumer.on(CRASH, ({ payload: { error, groupId } }) => {
        offsets = {}
        status.error('⚠️', `Kafka consumer group ${groupId} crashed:\n`, error)
        clearInterval(statusInterval)
        Sentry.captureException(error, {
            extra: { detected_at: `kafka-queue.ts on consumer crash` },
        })
        killGracefully()
    })
    consumer.on(CONNECT, () => {
        offsets = {}
        status.info('✅', 'Kafka consumer connected!')
    })
    consumer.on(DISCONNECT, () => {
        status.info('ℹ️', 'consumer_status', { groupId, offsets })
        offsets = {}
        clearInterval(statusInterval)
        status.info('🛑', 'Kafka consumer disconnected!')
    })
    consumer.on(COMMIT_OFFSETS, ({ payload: { topics } }) => {
        topics.forEach(({ topic, partitions }) => {
            partitions.forEach(({ partition, offset }) => {
                offsets[`${topic}:${partition}`] = offset
            })
        })
    })
}

type EachBatchHandler = (messages: Message[]) => Promise<void>

export const instrumentEachBatch = async (
    topic: string,
    eachBatch: EachBatchHandler,
    messages: Message[],
    statsd?: StatsD
): Promise<void> => {
    try {
        kafkaConsumerMessagesReadCounter.labels({ topic_name: topic }).inc(messages.length)
        await eachBatch(messages)
        kafkaConsumerMessagesProcessedCounter.labels({ topic_name: topic }).inc(messages.length)
    } catch (error) {
        const eventCount = messages.length
        statsd?.increment('kafka_queue_each_batch_failed_events', eventCount, {
            topic: topic,
        })
        status.warn('💀', `Kafka batch of ${eventCount} events for topic ${topic} failed!`)
        throw error
    }
}

export const instrumentEachBatchKafkaJS = async (
    topic: string,
    eachBatch: (payload: EachBatchPayload) => Promise<void>,
    payload: EachBatchPayload,
    statsd?: StatsD
): Promise<void> => {
    try {
        kafkaConsumerMessagesReadCounter.labels({ topic_name: topic }).inc(payload.batch.messages.length)
        await eachBatch(payload)
        kafkaConsumerMessagesProcessedCounter.labels({ topic_name: topic }).inc(payload.batch.messages.length)
    } catch (error) {
        const eventCount = payload.batch.messages.length
        statsd?.increment('kafka_queue_each_batch_failed_events', eventCount, {
            topic: topic,
        })
        status.warn('💀', `Kafka batch of ${eventCount} events for topic ${topic} failed!`, {
            stack: error.stack,
            error: error,
        })
        if (error.type === 'UNKNOWN_MEMBER_ID') {
            status.info('💀', "Probably the batch took longer than the session and we couldn't commit the offset")
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
                    statsd?.increment('each_batch_error_' + metricSuffix)
                    logToSentry = false
                }
            }
            if (logToSentry) {
                Sentry.captureException(error, {
                    extra: { detected_at: `kafka-queue.ts instrumentEachBatch` },
                })
            }
        }
        throw error
    }
}

export const kafkaConsumerMessagesReadCounter = new Counter({
    name: 'kafka_consumer_messages_read_total',
    help: 'Count of messages read Kafka consumer for processing, by source topic.',
    labelNames: ['topic_name'],
})

export const kafkaConsumerMessagesProcessedCounter = new Counter({
    name: 'kafka_consumer_messages_processed_total',
    help: 'Count of messages successfully processed by Kafka consumer, by source topic.',
    labelNames: ['topic_name'],
})
