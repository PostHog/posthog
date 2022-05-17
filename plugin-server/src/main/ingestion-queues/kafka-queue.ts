import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { Consumer, EachBatchPayload, Kafka, KafkaMessage } from 'kafkajs'

import { PluginServerMode } from '../../types'
import { Hub, Queue, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { groupIntoBatches, killGracefully, sanitizeEvent } from '../../utils/utils'
import { runInstrumentedFunction } from '../utils'
import { ingestEvent } from './ingest-event'

class DelayProcessing extends Error {}

type ConsumerManagementPayload = {
    topic: string
    partitions?: number[] | undefined
}
export class KafkaQueue implements Queue {
    private pluginsServer: Hub
    private kafka: Kafka
    private consumer: Consumer
    private wasConsumerRan: boolean
    private workerMethods: WorkerMethods
    private pluginServerMode: PluginServerMode
    private sleepTimeout: NodeJS.Timeout | null

    constructor(
        pluginsServer: Hub,
        workerMethods: WorkerMethods,
        pluginServerMode: PluginServerMode = PluginServerMode.Ingestion
    ) {
        this.pluginsServer = pluginsServer
        this.kafka = pluginsServer.kafka!
        this.pluginServerMode = pluginServerMode
        this.consumer = KafkaQueue.buildConsumer(
            this.kafka,
            pluginServerMode === PluginServerMode.Runner ? 'runner-consumer' : undefined
        )
        this.wasConsumerRan = false
        this.workerMethods = workerMethods
        this.sleepTimeout = null
    }

    private async eachMessageIngestion(message: KafkaMessage): Promise<void> {
        const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
        const combinedEvent = { ...rawEvent, ...JSON.parse(dataStr) }
        const event: PluginEvent = sanitizeEvent({
            ...combinedEvent,
            site_url: combinedEvent.site_url || null,
            ip: combinedEvent.ip || null,
        })
        await ingestEvent(this.pluginsServer, this.workerMethods, event)
    }

    private async eachMessageBuffer(
        message: KafkaMessage,
        resolveOffset: EachBatchPayload['resolveOffset']
    ): Promise<void> {
        const bufferEvent = JSON.parse(message.value!.toString())
        await runInstrumentedFunction({
            server: this.pluginsServer,
            event: bufferEvent,
            func: (_) => this.workerMethods.ingestBufferEvent(bufferEvent),
            statsKey: `kafka_queue.ingest_buffer_event`,
            timeoutMessage: 'After 30 seconds still running ingestBufferEvent',
        })
        resolveOffset(message.offset)
    }

    private async eachBatchBuffer({ batch, resolveOffset, commitOffsetsIfNecessary }: EachBatchPayload): Promise<void> {
        if (batch.messages.length === 0) {
            return
        }
        const batchStartTimer = new Date()

        let consumerSleep = 0
        for (const message of batch.messages) {
            // kafka timestamps are unix timestamps in string format
            const processAt = Number(message.timestamp) + this.pluginsServer.BUFFER_CONVERSION_SECONDS * 1000
            const delayUntilTimeToProcess = processAt - Date.now()

            if (delayUntilTimeToProcess < 0) {
                await this.eachMessageBuffer(message, resolveOffset)
            } else {
                consumerSleep = Math.max(consumerSleep, delayUntilTimeToProcess)
            }
        }

        // if consumerSleep > 0 it means we didn't process at least one message
        if (consumerSleep > 0) {
            // pause the consumer for this partition until we can process all unprocessed messages from this batch
            this.sleepTimeout = setTimeout(() => {
                if (this.sleepTimeout) {
                    clearTimeout(this.sleepTimeout)
                }
                this.resume(batch.topic, batch.partition)
            }, consumerSleep)
            await this.pause(batch.topic, batch.partition)

            // we throw an error to prevent the non-processed message offsets from being committed
            // from the kafkajs docs:
            // > resolveOffset() is used to mark a message in the batch as processed.
            // > In case of errors, the consumer will automatically commit the resolved offsets.
            throw new DelayProcessing()
        }

        await commitOffsetsIfNecessary()

        this.pluginsServer.statsd?.timing('kafka_queue.each_batch_buffer', batchStartTimer)
    }

    private async eachBatchIngestion({
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
                    status.info('🚪', `Bailing out of a batch of ${batch.messages.length} events`, {
                        isRunning: isRunning(),
                        isStale: isStale(),
                        msFromBatchStart: new Date().valueOf() - batchStartTimer.valueOf(),
                    })
                    return
                }

                await Promise.all(messageBatch.map((message) => this.eachMessageIngestion(message)))

                // this if should never be false, but who can trust computers these days
                if (messageBatch.length > 0) {
                    resolveOffset(messageBatch[messageBatch.length - 1].offset)
                }
                await commitOffsetsIfNecessary()
                await heartbeat()
            }

            status.info(
                '🧩',
                `Kafka batch of ${batch.messages.length} events completed in ${
                    new Date().valueOf() - batchStartTimer.valueOf()
                }ms`
            )
        } finally {
            this.pluginsServer.statsd?.timing('kafka_queue.each_batch', batchStartTimer)
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
            const ingestionTopic =
                this.pluginServerMode === PluginServerMode.Ingestion
                    ? this.pluginsServer.KAFKA_CONSUMPTION_TOPIC!
                    : this.pluginsServer.KAFKA_RUNNER_TOPIC!

            await this.consumer.subscribe({
                topic: ingestionTopic,
            })

            // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
            await this.consumer.run({
                eachBatchAutoResolve: false,
                autoCommitInterval: 1000, // autocommit every 1000 ms…
                autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
                partitionsConsumedConcurrently: this.pluginsServer.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
                eachBatch: async (payload) => {
                    const batchTopic = payload.batch.topic
                    try {
                        if (batchTopic === ingestionTopic) {
                            await this.eachBatchIngestion(payload)
                        } else {
                            await this.eachBatchBuffer(payload)
                        }
                    } catch (error) {
                        const eventCount = payload.batch.messages.length
                        this.pluginsServer.statsd?.increment('kafka_queue_each_batch_failed_events', eventCount, {
                            topic: batchTopic,
                        })
                        status.info('💀', `Kafka batch of ${eventCount} events for topic ${batchTopic} failed!`)
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

    resume(targetTopic: string = this.pluginsServer.KAFKA_CONSUMPTION_TOPIC!, partition?: number): void {
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

    isPaused(targetTopic: string = this.pluginsServer.KAFKA_CONSUMPTION_TOPIC!, partition?: number): boolean {
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
