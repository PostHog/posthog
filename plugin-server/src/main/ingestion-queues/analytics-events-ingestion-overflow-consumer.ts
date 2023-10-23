import { Message } from 'node-rdkafka'

import { KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { eachBatchParallelIngestion, IngestionOverflowMode } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

export const startAnalyticsEventsIngestionOverflowConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
}: {
    hub: Hub
}) => {
    /*
        Consumes analytics events from the Kafka topic `events_plugin_ingestion_overflow`
        and processes them for ingestion into ClickHouse.

        This is the overflow or "slow-lane" processing queue as it contains only events that
        have exceed capacity.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', 'Starting analytics events overflow consumer with rdkafka')

    // NOTE: we are explicitly not maintaining backwards compatibility with
    // previous functionality regards to consumer group id usage prior to the
    // introduction of this file. Previouslty, when ingestion and export
    // workloads ran on the same process they would share the same consumer
    // group id. In these cases, updating to this version will result in the
    // re-exporting of events still in Kafka `clickhouse_events_json` topic.

    const batchHandler = async (messages: Message[], queue: IngestionConsumer): Promise<void> => {
        await eachBatchParallelIngestion(messages, queue, IngestionOverflowMode.Consume)
    }

    const queue = new IngestionConsumer(
        hub,
        KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        `${KAFKA_PREFIX}clickhouse-ingestion-overflow`,
        batchHandler
    )

    await queue.start()

    return queue
}
