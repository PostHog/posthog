import { EachBatchPayload, KafkaMessage } from 'kafkajs'

import { KafkaConsumerName, PluginServerMode } from '../../../types'
import { Hub, WorkerMethods } from '../../../types'
import { runInstrumentedFunction } from '../../utils'
import { KAFKA_BUFFER } from './../../../config/kafka-topics'
import { KafkaQueue } from './kafka-queue'

class DelayProcessing extends Error {}
export class BufferQueue extends KafkaQueue {
    private workerMethods: WorkerMethods

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

        super(pluginsServer, consumer, KAFKA_BUFFER, KafkaConsumerName.Ingestion)
        this.workerMethods = workerMethods
    }

    private async eachMessage(message: KafkaMessage, resolveOffset: EachBatchPayload['resolveOffset']): Promise<void> {
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

    protected async runConsumer(): Promise<void> {
        // KafkaJS batching: https://kafka.js.org/docs/consuming#a-name-each-batch-a-eachbatch
        await this.consumer.run({
            eachBatchAutoResolve: false,
            autoCommitInterval: 1000,
            autoCommitThreshold: 1000,
            partitionsConsumedConcurrently: this.pluginsServer.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
            eachBatch: async ({ batch, commitOffsetsIfNecessary, resolveOffset }) => {
                if (batch.messages.length === 0) {
                    return
                }

                const promises = []
                let consumerSleep = 0
                for (const message of batch.messages) {
                    const processAt = new Date().getTime() + this.pluginsServer.BUFFER_CONVERSION_SECONDS * 1000
                    const delayUntilTimeToProcess = processAt - new Date(message.timestamp).getTime()
                    if (delayUntilTimeToProcess < 0) {
                        promises.push(this.eachMessage(message, resolveOffset))
                    } else {
                        consumerSleep = Math.max(consumerSleep, delayUntilTimeToProcess)
                    }
                }

                await Promise.all(promises)

                // if consumerSleep > 0 it means we didn't process at least one message
                if (consumerSleep > 0) {
                    // pause the consumer for this partition until we can process at least one message
                    await this.pause(batch.partition)
                    setTimeout(() => {
                        this.resume(batch.partition)
                    }, consumerSleep)

                    // we throw an error to prevent the non-processed message offsets from being committed
                    // from the kafkajs docs:
                    // > resolveOffset() is used to mark a message in the batch as processed.
                    // > In case of errors, the consumer will automatically commit the resolved offsets.
                    throw new DelayProcessing()
                }

                await commitOffsetsIfNecessary()
            },
        })
    }
}
