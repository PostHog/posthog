import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { Consumer, EachBatchPayload, Kafka, KafkaMessage } from 'kafkajs'

import { PluginServerMode } from '../../types'
import { Hub, Queue, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { groupIntoBatches, killGracefully, sanitizeEvent } from '../../utils/utils'
import { onEvent } from '../runner/on-event'
import { ingestEvent } from './ingest-event'

export class KafkaQueue implements Queue {
    private pluginsServer: Hub
    private kafka: Kafka
    private consumer: Consumer
    private wasConsumerRan: boolean
    private workerMethods: WorkerMethods
    private pluginServerMode: PluginServerMode

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
    }

    private async eachMessage(message: KafkaMessage): Promise<void> {
        if (this.pluginServerMode === PluginServerMode.Ingestion) {
            const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
            const combinedEvent = { ...rawEvent, ...JSON.parse(dataStr) }
            const event: PluginEvent = sanitizeEvent({
                ...combinedEvent,
                site_url: combinedEvent.site_url || null,
                ip: combinedEvent.ip || null,
            })
            await ingestEvent(this.pluginsServer, this.workerMethods, event)
        } else {
            const event = JSON.parse(message.value!.toString())
            await onEvent(this.pluginsServer, this.workerMethods, event)
        }
    }

    private async eachBatch({
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
            const topic =
                this.pluginServerMode === PluginServerMode.Ingestion
                    ? this.pluginsServer.KAFKA_CONSUMPTION_TOPIC!
                    : this.pluginsServer.KAFKA_RUNNER_TOPIC!

            await this.consumer.subscribe({
                topic,
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
                        this.pluginsServer.statsd?.increment('kafka_queue_each_batch_failed_events', eventCount)
                        status.info('💀', `Kafka batch of ${eventCount} events failed!`)
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

    async pause(): Promise<void> {
        if (this.wasConsumerRan && !this.isPaused()) {
            status.info('⏳', 'Pausing Kafka consumer...')
            this.consumer.pause([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
            status.info('⏸', 'Kafka consumer paused!')
        }
        return Promise.resolve()
    }

    resume(): void {
        if (this.wasConsumerRan && this.isPaused()) {
            status.info('⏳', 'Resuming Kafka consumer...')
            this.consumer.resume([{ topic: this.pluginsServer.KAFKA_CONSUMPTION_TOPIC! }])
            status.info('▶️', 'Kafka consumer resumed!')
        }
    }

    isPaused(): boolean {
        return this.consumer.paused().some(({ topic }) => topic === this.pluginsServer.KAFKA_CONSUMPTION_TOPIC)
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
