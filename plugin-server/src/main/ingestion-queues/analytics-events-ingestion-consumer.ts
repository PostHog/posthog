import Piscina from '@posthog/piscina'
import * as schedule from 'node-schedule'

import { KAFKA_EVENTS_PLUGIN_INGESTION, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { eachBatchIngestion } from './batch-processing/each-batch-ingestion'
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

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', 'Starting analytics events consumer')

    const queue = new IngestionConsumer(
        hub,
        piscina,
        [KAFKA_EVENTS_PLUGIN_INGESTION],
        `${KAFKA_PREFIX}clickhouse-ingestion`,
        eachBatchIngestion
    )

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    return queue
}
