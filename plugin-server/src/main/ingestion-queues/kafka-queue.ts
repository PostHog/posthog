import { Consumer, EachBatchPayload, Kafka } from 'kafkajs'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { Hub, PluginsServerConfig } from '../../types'
import { timeoutGuard } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { killGracefully } from '../../utils/utils'
import { addMetricsEventListeners } from './kafka-metrics'

/** Narrowed Hub type for KafkaJSIngestionConsumer */
export type KafkaJSIngestionConsumerHub = Pick<
    PluginsServerConfig,
    | 'KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS'
    | 'KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS'
    | 'KAFKA_HOSTS'
    | 'KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY'
> &
    Pick<Hub, 'kafka'>

type ConsumerManagementPayload = {
    topic: string
    partitions?: number[] | undefined
}

type KafkaJSBatchFunction = (payload: EachBatchPayload, queue: KafkaJSIngestionConsumer) => Promise<void>

export class KafkaJSIngestionConsumer {
    public pluginsServer: KafkaJSIngestionConsumerHub
    public consumerReady: boolean
    public topic: string
    public consumerGroupId: string
    public eachBatch: KafkaJSBatchFunction
    public consumer: Consumer
    public sessionTimeout: number
    private kafka: Kafka
    private wasConsumerRan: boolean

    constructor(
        pluginsServer: KafkaJSIngestionConsumerHub,
        topic: string,
        consumerGroupId: string,
        batchHandler: KafkaJSBatchFunction
    ) {
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
            addMetricsEventListeners(this.consumer)

            this.consumer.on(this.consumer.events.GROUP_JOIN, ({ payload }) => {
                logger.info('ℹ️', 'Kafka joined consumer group', JSON.stringify(payload))
                this.consumerReady = true
                clearTimeout(timeout)
                resolve()
            })
            this.consumer.on(this.consumer.events.CRASH, ({ payload: { error } }) => reject(error))
            logger.info('⏬', `Connecting Kafka consumer to ${this.pluginsServer.KAFKA_HOSTS}...`)
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
        await instrumentEachBatchKafkaJS(topic, (payload) => this.eachBatch(payload, this), payload)
    }

    async pause(targetTopic: string, partition?: number): Promise<void> {
        if (this.wasConsumerRan && !this.isPaused(targetTopic, partition)) {
            const pausePayload: ConsumerManagementPayload = { topic: targetTopic }
            let partitionInfo = ''
            if (partition) {
                pausePayload.partitions = [partition]
                partitionInfo = `(partition ${partition})`
            }

            logger.info('⏳', `Pausing Kafka consumer for topic ${targetTopic} ${partitionInfo}...`)
            this.consumer.pause([pausePayload])
            logger.info('⏸', `Kafka consumer for topic ${targetTopic} ${partitionInfo} paused!`)
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
            logger.info('⏳', `Resuming Kafka consumer for topic ${targetTopic} ${partitionInfo}...`)
            this.consumer.resume([resumePayload])
            logger.info('▶️', `Kafka consumer for topic ${targetTopic} ${partitionInfo}resumed!`)
        }
    }

    isPaused(targetTopic: string, partition?: number): boolean {
        // if we pass a partition, check that as well, else just return if the topic is paused
        return this.consumer
            .paused()
            .some(({ topic, partitions }) => topic === targetTopic && (!partition || partitions.includes(partition)))
    }

    async stop(): Promise<void> {
        logger.info('⏳', 'Stopping Kafka queue...')
        try {
            await this.consumer.stop()
            logger.info('⏹', 'Kafka consumer stopped!')
        } catch (error) {
            logger.error('⚠️', 'An error occurred while stopping Kafka queue:\n', error)
        }
        try {
            await this.consumer.disconnect()
        } catch {}

        this.consumerReady = false
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

export const setupEventHandlers = (consumer: Consumer): void => {
    const { GROUP_JOIN, CRASH, CONNECT, DISCONNECT, COMMIT_OFFSETS } = consumer.events
    let offsets: { [key: string]: string } = {} // Keep a record of offsets so we can report on process periodically
    let statusInterval: NodeJS.Timeout
    let groupId: string

    consumer.on(GROUP_JOIN, ({ payload }) => {
        offsets = {}
        groupId = payload.groupId
        logger.info('✅', `Kafka consumer joined group ${groupId}!`)
        clearInterval(statusInterval)
        statusInterval = setInterval(() => {
            logger.info('ℹ️', 'consumer_status', { groupId, offsets })
        }, 10000)
    })
    consumer.on(CRASH, ({ payload: { error, groupId } }) => {
        offsets = {}
        logger.error('⚠️', `Kafka consumer group ${groupId} crashed:\n`, error)
        clearInterval(statusInterval)
        captureException(error, {
            extra: { detected_at: `kafka-queue.ts on consumer crash` },
        })
        killGracefully()
    })
    consumer.on(CONNECT, () => {
        offsets = {}
        logger.info('✅', 'Kafka consumer connected!')
    })
    consumer.on(DISCONNECT, () => {
        logger.info('ℹ️', 'consumer_status', { groupId, offsets })
        offsets = {}
        clearInterval(statusInterval)
        logger.info('🛑', 'Kafka consumer disconnected!')
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
    messages: Message[]
): Promise<void> => {
    try {
        kafkaConsumerMessagesReadCounter.labels({ topic_name: topic }).inc(messages.length)
        await eachBatch(messages)
        kafkaConsumerMessagesProcessedCounter.labels({ topic_name: topic }).inc(messages.length)
    } catch (error) {
        const eventCount = messages.length
        kafkaConsumerEachBatchFailedCounter.labels({ topic_name: topic }).inc(eventCount)
        logger.warn('💀', `Kafka batch of ${eventCount} events for topic ${topic} failed!`)
        throw error
    }
}

export const instrumentEachBatchKafkaJS = async (
    topic: string,
    eachBatch: (payload: EachBatchPayload) => Promise<void>,
    payload: EachBatchPayload
): Promise<void> => {
    try {
        kafkaConsumerMessagesReadCounter.labels({ topic_name: topic }).inc(payload.batch.messages.length)
        await eachBatch(payload)
        kafkaConsumerMessagesProcessedCounter.labels({ topic_name: topic }).inc(payload.batch.messages.length)
    } catch (error) {
        const eventCount = payload.batch.messages.length
        kafkaConsumerEachBatchFailedCounter.labels({ topic_name: topic }).inc(eventCount)
        logger.warn('💀', `Kafka batch of ${eventCount} events for topic ${topic} failed!`, {
            stack: error.stack,
            error: error,
        })
        if (error.type === 'UNKNOWN_MEMBER_ID') {
            logger.info('💀', "Probably the batch took longer than the session and we couldn't commit the offset")
        }
        if (error.message) {
            let sendException = true
            const messagesToIgnore = {
                'The group is rebalancing, so a rejoin is needed': 'group_rebalancing',
                'Specified group generation id is not valid': 'generation_id_invalid',
                'Could not find person with distinct id': 'person_not_found',
                'The coordinator is not aware of this member': 'not_aware_of_member',
            }
            for (const [msg, _] of Object.entries(messagesToIgnore)) {
                if (error.message.includes(msg)) {
                    sendException = false
                }
            }
            if (sendException) {
                captureException(error, {
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

export const kafkaConsumerEachBatchFailedCounter = new Counter({
    name: 'kafka_consumer_each_batch_failed_total',
    help: 'Count of each batch failures by source topic.',
    labelNames: ['topic_name'],
})
