import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { Consumer, EachBatchPayload } from 'kafkajs'
import { Message } from 'node-rdkafka-acosom'

import { BatchConsumer, startBatchConsumer } from '../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../kafka/config'
import { Hub, PipelineEvent, PostIngestionEvent, WorkerMethods } from '../../types'
import { KafkaConfig } from '../../utils/db/hub'
import { status } from '../../utils/status'
import { killGracefully } from '../../utils/utils'
import Piscina from '../../worker/piscina'

type EachBatchFunction = (messages: Message[], queue: IngestionConsumer) => Promise<void>

export class IngestionConsumer {
    public pluginsServer: Hub
    public workerMethods: WorkerMethods
    public consumerReady: boolean
    public topic: string
    public consumerGroupId: string
    public eachBatch: EachBatchFunction
    public consumer?: BatchConsumer

    constructor(
        pluginsServer: Hub,
        piscina: Piscina,
        topic: string,
        consumerGroupId: string,
        batchHandler: EachBatchFunction
    ) {
        this.pluginsServer = pluginsServer
        this.topic = topic
        this.consumerGroupId = consumerGroupId

        // TODO: remove `this.workerMethods` and just rely on
        // `this.batchHandler`. At the time of writing however, there are some
        // references to queue.workerMethods buried deep in the codebase
        // #onestepatatime
        this.workerMethods = {
            runAsyncHandlersEventPipeline: (event: PostIngestionEvent) => {
                this.pluginsServer.lastActivity = new Date().valueOf()
                this.pluginsServer.lastActivityType = 'runAsyncHandlersEventPipeline'
                return piscina.run({ task: 'runAsyncHandlersEventPipeline', args: { event } })
            },
            runEventPipeline: (event: PipelineEvent) => {
                this.pluginsServer.lastActivity = new Date().valueOf()
                this.pluginsServer.lastActivityType = 'runEventPipeline'
                return piscina.run({ task: 'runEventPipeline', args: { event } })
            },
        }
        this.consumerReady = false

        this.eachBatch = batchHandler
    }

    async start(): Promise<BatchConsumer> {
        // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
        this.consumer = await startBatchConsumer({
            connectionConfig: createRdConnectionConfigFromEnvVars(this.pluginsServer as KafkaConfig),
            topic: this.topic,
            groupId: this.consumerGroupId,
            sessionTimeout: 30000,
            consumerMaxBytes: this.pluginsServer.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.pluginsServer.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            consumerMaxWaitMs: this.pluginsServer.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            fetchBatchSize: 500,
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
        await eachBatch(messages)
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
        await eachBatch(payload)
    } catch (error) {
        const eventCount = payload.batch.messages.length
        statsd?.increment('kafka_queue_each_batch_failed_events', eventCount, {
            topic: topic,
        })
        status.warn('💀', `Kafka batch of ${eventCount} events for topic ${topic} failed!`)
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
