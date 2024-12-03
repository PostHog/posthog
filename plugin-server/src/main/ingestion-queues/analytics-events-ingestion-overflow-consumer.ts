import { Message } from 'node-rdkafka'

import { buildStringMatcher } from '../../config/config'
import { KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { isOverflowBatchByDistinctId } from '../../utils/env-utils'
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
    const tokenBlockList = buildStringMatcher(hub.DROP_EVENTS_BY_TOKEN, false)
    const overflowMode = isOverflowBatchByDistinctId()
        ? IngestionOverflowMode.ConsumeSplitByDistinctId
        : IngestionOverflowMode.ConsumeSplitEvenly
    const batchHandler = async (messages: Message[], queue: IngestionConsumer): Promise<void> => {
        await eachBatchParallelIngestion(tokenBlockList, messages, queue, overflowMode)
    }

    const queue = new IngestionConsumer(
        hub,
        KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        `${KAFKA_PREFIX}clickhouse-ingestion-overflow`,
        batchHandler
    )

    await queue.start()

    const { isHealthy } = await queue.start()

    return {
        id: 'analytics-ingestion-overflow',
        onShutdown: async () => await queue.stop(),
        healthcheck: isHealthy,
        batchConsumer: queue.consumer,
    }
}
