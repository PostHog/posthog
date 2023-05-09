import { Message } from 'node-rdkafka-acosom'
import { Counter } from 'prom-client'

import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    prefix as KAFKA_PREFIX,
} from '../../config/kafka-topics'
import { Hub } from '../../types'
import { isIngestionOverflowEnabled } from '../../utils/env-utils'
import { formPipelineEvent } from '../../utils/event'
import { status } from '../../utils/status'
import { ConfiguredLimiter, LoggingLimiter } from '../../utils/token-bucket'
import Piscina from '../../worker/piscina'
import { eachBatch } from './batch-processing/each-batch'
import { eachBatchIngestion, eachMessageIngestion } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

export const ingestionPartitionKeyOverflowed = new Counter({
    name: 'ingestion_partition_key_overflowed',
    help: 'Indicates that a given key has overflowed capacity and been redirected to a different topic. Value incremented once a minute.',
    labelNames: ['partition_key'],
})

export const startAnalyticsEventsIngestionConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    piscina,
}: {
    hub: Hub
    piscina: Piscina
}) => {
    /*
        Consumes analytics events from the Kafka topic `events_plugin_ingestion`
        and processes them for ingestion into ClickHouse.

        Before processing, if isIngestionOverflowEnabled and an event has
        overflowed the capacity for its (team_id, distinct_id) pair, it will not
        be processed here but instead re-produced into the
        `events_plugin_ingestion_overflow` topic for later processing.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', 'Starting analytics events consumer')

    // NOTE: we are explicitly not maintaining backwards compatibility with
    // previous functionality regards to consumer group id usage prior to the
    // introduction of this file. Previouslty, when ingestion and export
    // workloads ran on the same process they would share the same consumer
    // group id. In these cases, updating to this version will result in the
    // re-exporting of events still in Kafka `clickhouse_events_json` topic.

    // We need a way to determine if ingestionOverflow is enabled when using
    // separate deployments for ingestion consumers in order to scale them
    // independently. Since ingestionOverflow may be enabled in a separate
    // deployment, we require an env variable to be set to confirm this before
    // enabling re-production of events to the OVERFLOW topic.
    const batchHandler = isIngestionOverflowEnabled() ? eachBatchIngestionWithOverflow : eachBatchIngestion

    const queue = new IngestionConsumer(
        hub,
        piscina,
        KAFKA_EVENTS_PLUGIN_INGESTION,
        `${KAFKA_PREFIX}clickhouse-ingestion`,
        batchHandler
    )

    const { isHealthy } = await queue.start()

    return { queue, isHealthy }
}

export async function eachBatchIngestionWithOverflow(payload: Message[], queue: IngestionConsumer): Promise<void> {
    function groupIntoBatchesIngestion(kafkaMessages: Message[], batchSize: number): Message[][] {
        // Once we see a distinct ID we've already seen break up the batch
        const batches = []
        const seenIds: Set<string> = new Set()
        let currentBatch: Message[] = []

        for (const message of kafkaMessages) {
            const pluginEvent = formPipelineEvent(message)
            // NOTE: we need to ensure that we either use the team_id or the
            // token whilst we haven't fully rolled out lightweight capture i.e.
            // we can't rely on token being set.
            const seenKey = `${pluginEvent.team_id ?? pluginEvent.token}:${pluginEvent.distinct_id}`

            // Events with a null key should have been produced to the the
            // KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW topic, so we shouldn't see them here as this consumer's
            // topic is set to KAFKA_EVENTS_PLUGIN_INGESTION. However, there could be some lingering events
            // from before the new *_OVERFLOW topic was initialized. Any events with a null key or that
            // exceed capacity are redirected to the *_OVERFLOW topic.
            if (message.key == null || ConfiguredLimiter.consume(seenKey, 1) === false) {
                // Set message key to be null so we know to send it to overflow topic.
                // We don't want to do it here to preserve the kafka offset handling
                message.key = null

                // To reduce cardinality, we only use the `team_id` or `token` as label.
                ingestionPartitionKeyOverflowed.labels(`${pluginEvent.team_id ?? pluginEvent.token}`).inc()

                if (LoggingLimiter.consume(seenKey, 1) === true) {
                    status.warn('🪣', `Partition key ${seenKey} overflowed ingestion capacity`)
                }
            }

            if (currentBatch.length >= batchSize || (message.key != null && seenIds.has(seenKey))) {
                seenIds.clear()
                batches.push(currentBatch)
                currentBatch = []
            }

            currentBatch.push(message)

            if (message.key != null) {
                seenIds.add(seenKey)
            }
        }

        if (currentBatch) {
            batches.push(currentBatch)
        }

        return batches
    }

    await eachBatch(payload, queue, eachMessageIngestionWithOverflow, groupIntoBatchesIngestion, 'ingestion')
}

export async function eachMessageIngestionWithOverflow(message: Message, queue: IngestionConsumer): Promise<void> {
    // Events are marked to have a null key during batch break-up if they should go to the *_OVERFLOW topic.
    // So we do not ingest them here.
    if (message.key == null) {
        await queue.pluginsServer.kafkaProducer.produce({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: message.value,
            key: message.key,
            headers: message.headers,
        })

        return
    }

    await eachMessageIngestion(message, queue)
}
