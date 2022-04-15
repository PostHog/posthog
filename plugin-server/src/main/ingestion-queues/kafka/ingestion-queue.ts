import { PluginEvent } from '@posthog/plugin-scaffold'
import { KafkaMessage } from 'kafkajs'

import { KafkaConsumerName, PluginServerMode } from '../../../types'
import { Hub, WorkerMethods } from '../../../types'
import { sanitizeEvent } from '../../../utils/utils'
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

    protected async eachMessage(message: KafkaMessage): Promise<void> {
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
}
