import { KafkaMessage } from 'kafkajs'

import { KafkaConsumerName, PluginServerMode } from '../../../types'
import { Hub, WorkerMethods } from '../../../types'
import { runInstrumentedFunction } from '../../utils'
import { KAFKA_BUFFER } from './../../../config/kafka-topics'
import { KafkaQueue } from './kafka-queue'

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

    protected async eachMessage(message: KafkaMessage): Promise<void> {
        const bufferEvent = JSON.parse(message.value!.toString())
        await runInstrumentedFunction({
            server: this.pluginsServer,
            event: bufferEvent,
            func: (_) => this.workerMethods.ingestBufferEvent(bufferEvent),
            statsKey: `kafka_queue.ingest_buffer_event`,
            timeoutMessage: 'After 30 seconds still running ingestBufferEvent',
        })
    }
}
