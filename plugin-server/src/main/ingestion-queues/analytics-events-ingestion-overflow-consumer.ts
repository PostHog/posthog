import Piscina from '@posthog/piscina'
import { EachBatchPayload, KafkaMessage } from 'kafkajs'
import * as schedule from 'node-schedule'

import { KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { formPipelineEvent } from '../../utils/event'
import { status } from '../../utils/status'
import { WarningLimiter } from '../../utils/token-bucket'
import { groupIntoBatches } from '../../utils/utils'
import { captureIngestionWarning } from './../../worker/ingestion/utils'
import { eachBatch } from './batch-processing/each-batch'
import { eachMessageIngestion } from './batch-processing/each-batch-ingestion'
import { IngestionConsumer } from './kafka-queue'

export const startAnalyticsEventsIngestionOverflowConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    piscina,
}: {
    hub: Hub
    piscina: Piscina
}) => {
    /*
        Consumes analytics events from the Kafka topic `events_plugin_ingestion_overflow`
        and processes them for ingestion into ClickHouse.

        This is the overflow or "slow-lane" processing queue as it contains only events that
        have exceed capacity.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', 'Starting analytics events overflow consumer')

    // NOTE: we are explicitly not maintaining backwards compatibility with
    // previous functionality regards to consumer group id usage prior to the
    // introduction of this file. Previouslty, when ingestion and export
    // workloads ran on the same process they would share the same consumer
    // group id. In these cases, updating to this version will result in the
    // re-exporting of events still in Kafka `clickhouse_events_json` topic.

    const queue = new IngestionConsumer(
        hub,
        piscina,
        KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
        `${KAFKA_PREFIX}clickhouse-ingestion-overflow`,
        eachBatchIngestionFromOverflow
    )

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    return queue
}

export async function eachBatchIngestionFromOverflow(
    payload: EachBatchPayload,
    queue: IngestionConsumer
): Promise<void> {
    await eachBatch(payload, queue, eachMessageIngestionFromOverflow, groupIntoBatches, 'ingestion')
}

export async function eachMessageIngestionFromOverflow(message: KafkaMessage, queue: IngestionConsumer): Promise<void> {
    const pluginEvent = formPipelineEvent(message)
    // Warnings are limited to 1/key/hour to avoid spamming.
    // TODO: now that we use lightweight capture, we need to ensure that we
    // resolve the team_id, as at the moment it will always be null.
    if (pluginEvent.team_id && WarningLimiter.consume(`${pluginEvent.team_id}:${pluginEvent.distinct_id}`, 1)) {
        captureIngestionWarning(queue.pluginsServer.db, pluginEvent.team_id, 'ingestion_capacity_overflow', {
            overflowDistinctId: pluginEvent.distinct_id,
        })
    }

    await eachMessageIngestion(message, queue)
}
