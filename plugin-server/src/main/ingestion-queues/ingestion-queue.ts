import * as Sentry from '@sentry/node'

import { Hub, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { KAFKA_BUFFER } from './../../config/kafka-topics'
import { eachBatchBuffer } from './buffer'
import { eachBatchIngestion } from './ingest-event'
import { KafkaQueue } from './kafka-queue'

const CONSUMER_NAME = 'main-ingestion-consumer'

export class IngestionQueue extends KafkaQueue {
    workerMethods: WorkerMethods
    sleepTimeout: NodeJS.Timeout | null
    ingestionTopic: string
    bufferTopic: string

    constructor(pluginsServer: Hub, workerMethods: WorkerMethods) {
        const kafka = pluginsServer.kafka!
        const consumer = KafkaQueue.buildConsumer(kafka, CONSUMER_NAME, undefined)

        const ingestionTopic = pluginsServer.KAFKA_CONSUMPTION_TOPIC!
        const bufferTopic = KAFKA_BUFFER

        const topics = [ingestionTopic]

        super(pluginsServer, consumer, topics)

        this.ingestionTopic = ingestionTopic
        this.bufferTopic = bufferTopic
        this.sleepTimeout = null
        this.workerMethods = workerMethods
    }

    async runConsumer(): Promise<void> {
        // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
        await this.consumer.run({
            eachBatchAutoResolve: false,
            autoCommitInterval: 1000, // autocommit every 1000 ms…
            autoCommitThreshold: 1000, // …or every 1000 messages, whichever is sooner
            partitionsConsumedConcurrently: this.pluginsServer.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
            eachBatch: async (payload) => {
                const batchTopic = payload.batch.topic
                try {
                    if (batchTopic === this.ingestionTopic) {
                        await eachBatchIngestion(payload, this)
                    } else if (batchTopic === this.bufferTopic) {
                        // currently this never runs - it depends on us subscribing to the buffer topic
                        await eachBatchBuffer(payload, this)
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
    }
}
