import { EachBatchPayload } from 'kafkajs'
import { Message } from 'node-rdkafka'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'

import { KAFKA_EVENTS_PLUGIN_INGESTION, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { isIngestionOverflowEnabled } from '../../utils/env-utils'
import { status } from '../../utils/status'
import Piscina from '../../worker/piscina'
import { eachBatchParallelIngestion, IngestionOverflowMode } from './batch-processing/each-batch-ingestion'
import { eachBatchLegacyIngestion } from './batch-processing/each-batch-ingestion-kafkajs'
import { IngestionConsumer, KafkaJSIngestionConsumer } from './kafka-queue'
import { makeHealthCheck } from './on-event-handler-consumer'

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
    if (!hub.KAFKA_CONSUMPTION_USE_RDKAFKA) {
        return startLegacyAnalyticsEventsIngestionConsumer({ hub, piscina })
    }
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

    const overflowMode = isIngestionOverflowEnabled() ? IngestionOverflowMode.Reroute : IngestionOverflowMode.Disabled
    const batchHandler = async (messages: Message[], queue: IngestionConsumer): Promise<void> => {
        await eachBatchParallelIngestion(messages, queue, overflowMode)
    }

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

const startLegacyAnalyticsEventsIngestionConsumer = async ({
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
    status.info('🔁', 'Starting analytics events consumer with kafkajs')

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

    const overflowMode = isIngestionOverflowEnabled() ? IngestionOverflowMode.Reroute : IngestionOverflowMode.Disabled
    const batchHandler = async (payload: EachBatchPayload, queue: KafkaJSIngestionConsumer): Promise<void> => {
        await eachBatchLegacyIngestion(payload, queue, overflowMode)
    }

    const queue = new KafkaJSIngestionConsumer(
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

    // Subscribe to the heatbeat event to track when the consumer has last
    // successfully consumed a message. This is used to determine if the
    // consumer is healthy.
    const isHealthy = makeHealthCheck(queue.consumer, queue.sessionTimeout)

    return { queue, isHealthy }
}
