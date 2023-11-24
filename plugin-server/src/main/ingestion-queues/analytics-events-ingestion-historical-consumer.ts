import { Message } from 'node-rdkafka'

import { buildStringMatcher } from '../../config/config'
import { KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { eachBatchParallelIngestion, IngestionOverflowMode } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

export const startAnalyticsEventsIngestionHistoricalConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
}: {
    hub: Hub
}) => {
    /*
        Consumes analytics events from the Kafka topic `events_plugin_ingestion_historical`
        and processes them for ingestion into ClickHouse.

        This is the historical events or "slow-lane" processing queue as it contains only
        events that have timestamps in the past.
    */
    status.info('🔁', 'Starting analytics events historical consumer with rdkafka')

    /*
        We don't want to move events to overflow from here, it's fine for the processing to
        take longer, but we want the locality constraints to be respected like normal ingestion.
    */
    const tokenBlockList = buildStringMatcher(hub.DROP_EVENTS_BY_TOKEN, false)
    const batchHandler = async (messages: Message[], queue: IngestionConsumer): Promise<void> => {
        await eachBatchParallelIngestion(tokenBlockList, messages, queue, IngestionOverflowMode.Disabled)
    }

    const queue = new IngestionConsumer(
        hub,
        KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
        `${KAFKA_PREFIX}clickhouse-ingestion-historical`,
        batchHandler
    )

    const { isHealthy } = await queue.start()

    return { queue, isHealthy }
}
