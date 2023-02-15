import Piscina from '@posthog/piscina'
import * as schedule from 'node-schedule'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import { eachBatchAsyncHandlers } from './batch-processing/each-batch-async-handlers'
import { IngestionConsumer } from './kafka-queue'

export const startOnEventHandlerConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    piscina,
}: {
    hub: Hub
    piscina: Piscina
}) => {
    /*
        Consumes analytics events from the Kafka topic `clickhouse_events_json`
        and processes any onEvent plugin handlers configured for the team. This
        also includes `exportEvents` handlers defined in plugins as these are
        also handled via modifying `onEvent` to call `exportEvents`.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', 'Starting onEvent handler consumer')

    // NOTE: to maintain backwards compatibility with how `IngestionConsumer`
    // consumer group id selection worked prior to the addition of this file, we
    // use the ingestion consumer group id if ingestion is enabled. Otherwise we
    // on updating to this version will end up switching consumer group ids and
    // therefore offsets, meaning we'd reprocess all events in the
    // `clickhouse_events_json` topic.
    // TODO: create and use a new topic for this consumer so we can have a
    // proper cut over
    const consumerGroupId = hub.capabilities.ingestion
        ? `${KAFKA_PREFIX}clickhouse-ingestion`
        : `${KAFKA_PREFIX}clickhouse-plugin-server-async`

    const queue = new IngestionConsumer(hub, piscina, [KAFKA_EVENTS_JSON], consumerGroupId, eachBatchAsyncHandlers)

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    return queue
}
