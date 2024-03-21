import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { buildStringMatcher } from '../../config/config'
import { KAFKA_EVENTS_PLUGIN_INGESTION, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { eachBatchParallelIngestion, IngestionOverflowMode } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

export const ingestionPartitionKeyOverflowed = new Counter({
    name: 'ingestion_partition_key_overflowed',
    help: 'Indicates that a given key has overflowed capacity and been redirected to a different topic. Value incremented once a minute.',
    labelNames: ['partition_key'],
})

export const startAnalyticsEventsIngestionConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
}: {
    hub: Hub
}) => {
    /*
        Consumes analytics events from the Kafka topic `events_plugin_ingestion`
        and processes them for ingestion into ClickHouse.

        Before processing, if overflow rerouting is enabled and an event has
        overflowed the capacity for its (team_id, distinct_id) pair, it will not
        be processed here but instead re-produced into the
        `events_plugin_ingestion_overflow` topic for later processing.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', 'Starting analytics events consumer with rdkafka')

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

    const overflowMode = hub.INGESTION_OVERFLOW_ENABLED
        ? hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY
            ? IngestionOverflowMode.Reroute
            : IngestionOverflowMode.RerouteRandomly
        : IngestionOverflowMode.Disabled

    const tokenBlockList = buildStringMatcher(hub.DROP_EVENTS_BY_TOKEN, false)
    const batchHandler = async (messages: Message[], queue: IngestionConsumer): Promise<void> => {
        await eachBatchParallelIngestion(tokenBlockList, messages, queue, overflowMode)
    }

    const queue = new IngestionConsumer(
        hub,
        KAFKA_EVENTS_PLUGIN_INGESTION,
        `${KAFKA_PREFIX}clickhouse-ingestion`,
        batchHandler
    )

    const { isHealthy } = await queue.start()

    return { queue, isHealthy }
}
