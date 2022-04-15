import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { KafkaConsumerName, PluginServerMode } from '../../../types'
import { Hub, WorkerMethods } from '../../../types'
import { status } from '../../../utils/status'
import { sanitizeEvent } from '../../../utils/utils'
import { groupIntoBatches } from '../../../utils/utils'
import { onEvent } from '../../runner/on-event'
import { ingestEvent } from '../ingest-event'
import { KafkaQueue } from './kafka-queue'

export class IngestionQueue extends KafkaQueue {
    private workerMethods: WorkerMethods
    private pluginServerMode: PluginServerMode

    constructor(
        pluginsServer: Hub,
        workerMethods: WorkerMethods,
        pluginServerMode: PluginServerMode = PluginServerMode.Ingestion
    ) {
        const kafka = pluginsServer.kafka!
        const consumer = KafkaQueue.buildConsumer(
            kafka,
            KafkaConsumerName.Ingestion,
            pluginServerMode === PluginServerMode.Runner ? 'runner-consumer' : undefined
        )
        const topic =
            pluginServerMode === PluginServerMode.Ingestion
                ? pluginsServer.KAFKA_CONSUMPTION_TOPIC!
                : pluginsServer.KAFKA_RUNNER_TOPIC!

        super(pluginsServer, consumer, topic, KafkaConsumerName.Ingestion)

        this.workerMethods = workerMethods
        this.pluginServerMode = pluginServerMode
    }

    private async eachMessage(message: KafkaMessage): Promise<void> {
        // Currently the else part is never triggered. The plugin server can only be
        // in "ingestion" mode at the moment, and onEvent is triggered in ingestEvent
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

    protected async runConsumer(): Promise<void> {
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
    }
}
