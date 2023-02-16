import Piscina from '@posthog/piscina'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'
import * as schedule from 'node-schedule'

import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
    prefix as KAFKA_PREFIX,
} from '../../config/kafka-topics'
import { Hub } from '../../types'
import { isIngestionOverflowEnabled } from '../../utils/env-utils'
import { formPipelineEvent } from '../../utils/event'
import { status } from '../../utils/status'
import { ConfiguredLimiter, WarningLimiter } from '../../utils/token-bucket'
import { captureIngestionWarning } from './../../worker/ingestion/utils'
import { eachBatch } from './batch-processing/each-batch'
import { eachBatchIngestion, eachMessageIngestion } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

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

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    return queue
}

export async function eachBatchIngestionWithOverflow(
    payload: EachBatchPayload,
    queue: IngestionConsumer
): Promise<void> {
    function groupIntoBatchesIngestion(kafkaMessages: KafkaMessage[], batchSize: number): KafkaMessage[][] {
        // Once we see a distinct ID we've already seen break up the batch
        const batches = []
        const seenIds: Set<string> = new Set()
        let currentBatch: KafkaMessage[] = []
        for (const message of kafkaMessages) {
            const pluginEvent = formPipelineEvent(message)
            const seenKey = `${pluginEvent.team_id}:${pluginEvent.distinct_id}`
            if (currentBatch.length === batchSize || seenIds.has(seenKey)) {
                seenIds.clear()
                batches.push(currentBatch)
                currentBatch = []
            }
            seenIds.add(seenKey)
            currentBatch.push(message)
        }
        if (currentBatch) {
            batches.push(currentBatch)
        }
        return batches
    }

    await eachBatch(payload, queue, eachMessageIngestionWithOverflow, groupIntoBatchesIngestion, 'ingestion')
}

export async function eachMessageIngestionWithOverflow(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    const event = formPipelineEvent(message)

    if (
        // Events with a null key are produced to the the KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW topic, so we would
        // never see them here, as this consumer's topic is set to KAFKA_EVENTS_PLUGIN_INGESTION.
        // However, there could be some lingering events from before the new *_OVERFLOW topic was initialized.
        // As we cannot accurately estimate capacity usage for those events, we will process them normally.
        // Once lingering events are cleared up, this check is not be needed anymore except for type-checking.
        message.key != null &&
        ConfiguredLimiter.consume(message.key.toString(), 1) === false
    ) {
        if (event.team_id && WarningLimiter.consume(message.key.toString(), 1)) {
            captureIngestionWarning(queue.pluginsServer.hub.db, event.team_id, 'ingestion_capacity_overflow', {
                overflowDistinctId: event.distinct_id,
            })
        }
        // Events going to OVERFLOW topic should always be randomly partitioned.
        message.key = null

        await queue.pluginsServer.kafkaProducer.queueMessage({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            messages: [message],
        })
    }

    await eachMessageIngestion(message, queue)
}
