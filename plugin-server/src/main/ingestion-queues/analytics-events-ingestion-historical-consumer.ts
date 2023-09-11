import { EachBatchPayload } from 'kafkajs'
import { Message } from 'node-rdkafka'
import * as schedule from 'node-schedule'

import { KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import Piscina from '../../worker/piscina'
import { eachBatchParallelIngestion, IngestionOverflowMode } from './batch-processing/each-batch-ingestion'
import { eachBatchLegacyIngestion } from './batch-processing/each-batch-ingestion-kafkajs'
import { IngestionConsumer, KafkaJSIngestionConsumer } from './kafka-queue'
import { makeHealthCheck } from './on-event-handler-consumer'

export const startAnalyticsEventsIngestionHistoricalConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    piscina,
}: {
    hub: Hub
    piscina: Piscina
}) => {
    if (!hub.KAFKA_CONSUMPTION_USE_RDKAFKA) {
        return startLegacyAnalyticsEventsIngestionHistoricalConsumer({ hub, piscina })
    }
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
    const batchHandler = async (messages: Message[], queue: IngestionConsumer): Promise<void> => {
        await eachBatchParallelIngestion(messages, queue, IngestionOverflowMode.Disabled)
    }

    const queue = new IngestionConsumer(
        hub,
        piscina,
        KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
        `${KAFKA_PREFIX}clickhouse-ingestion-historical`,
        batchHandler
    )

    const { isHealthy } = await queue.start()

    return { queue, isHealthy }
}

export const startLegacyAnalyticsEventsIngestionHistoricalConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    piscina,
}: {
    hub: Hub
    piscina: Piscina
}) => {
    /*
        Consumes analytics events from the Kafka topic `events_plugin_ingestion_historical`
        and processes them for ingestion into ClickHouse.

        This is the historical events or "slow-lane" processing queue as it contains only
        events that have timestamps in the past.
    */
    status.info('🔁', 'Starting analytics events historical consumer with kafkajs')

    /*
        We don't want to move events to overflow from here, it's fine for the processing to
        take longer, but we want the locality constraints to be respected like normal ingestion.
    */
    const batchHandler = async (payload: EachBatchPayload, queue: KafkaJSIngestionConsumer): Promise<void> => {
        await eachBatchLegacyIngestion(payload, queue, IngestionOverflowMode.Disabled)
    }

    const queue = new KafkaJSIngestionConsumer(
        hub,
        piscina,
        KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
        `${KAFKA_PREFIX}clickhouse-ingestion-historical`,
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
