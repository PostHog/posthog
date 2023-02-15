import Piscina from '@posthog/piscina'
import * as schedule from 'node-schedule'

import { KAFKA_EVENTS_JSON, KAFKA_EVENTS_PLUGIN_INGESTION, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { eachBatchAsyncHandlers } from './batch-processing/each-batch-async-handlers'
import { eachBatchIngestion } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

export const startAnalyticsEventsIngestionConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    piscina,
    alsoProcessExportEvents,
}: {
    hub: Hub
    piscina: Piscina
    alsoProcessExportEvents: boolean
}) => {
    /*
        Consumes analytics events from the Kafka topic `events_plugin_ingestion`
        and processes them for ingestion into ClickHouse.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', 'Starting analytics events consumer')

    // NOTE: to maintain backwards compatibility with how `IngestionConsumer`
    // consumer group id selection worked prior to the addition of this file, we
    // need to consume _with the same consumer group id_ as the
    // `clickhouse_events_json` topic. We need to do this because if we try to
    // use separate consumers with the same consumer id we'll get issues with
    // partition allocation. We can't use a new consumer group id because we
    // want to ensure that we don't re-export the same events again due to the
    // offsets being new for this consumer group id.
    // TODO: create and use a new topic for this consumer so we can have a
    // proper cut over. We'll need to ensure we are also consuming from the old
    // topic for some period of time to ensure we don't miss any events. We'll
    // also need to play around with the ClickHouse Kafka Table which would also
    // need to do the same dance. Alternatively we can simply use a different
    // topic for exports and ClickHouse ingestion.
    const topics = alsoProcessExportEvents
        ? [KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_EVENTS_JSON]
        : [KAFKA_EVENTS_PLUGIN_INGESTION]

    const queue = new IngestionConsumer(
        hub,
        piscina,
        topics,
        `${KAFKA_PREFIX}clickhouse-ingestion`,
        async (payload, queue) => {
            if (payload.batch.topic === KAFKA_EVENTS_PLUGIN_INGESTION) {
                await eachBatchIngestion(payload, queue)
            } else if (payload.batch.topic === KAFKA_EVENTS_JSON) {
                await eachBatchAsyncHandlers(payload, queue)
            }
        }
    )

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    return queue
}
