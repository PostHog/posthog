import * as schedule from 'node-schedule'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub } from '../../types'
import { status } from '../../utils/status'
import Piscina from '../../worker/piscina'
import {
    eachBatchAppsOnEventHandlers,
    eachBatchAsyncHandlers,
    eachBatchWebhooksHandlers,
} from './batch-processing/each-batch-async-handlers'
import { KafkaJSIngestionConsumer } from './kafka-queue'

export const startAsyncHandlerConsumer = async ({
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
    status.info('🔁', `Starting async handler consumer`)

    const queue = buildAsyncIngestionConsumer({ hub, piscina })

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    const isHealthy = makeHealthCheck(queue)

    return { queue, isHealthy: () => isHealthy() }
}

export const startAsyncOnEventHandlerConsumer = async ({
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
    status.info('🔁', `Starting onEvent handler consumer`)

    const queue = buildOnEventIngestionConsumer({ hub, piscina })

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    const isHealthy = makeHealthCheck(queue)

    return { queue, isHealthy: () => isHealthy() }
}

export const startAsyncWebhooksHandlerConsumer = async ({
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
    status.info('🔁', `Starting webhooks handler consumer`)

    const queue = buildWebhooksIngestionConsumer({ hub, piscina })

    await queue.start()

    schedule.scheduleJob('0 * * * * *', async () => {
        await queue.emitConsumerGroupMetrics()
    })

    const isHealthy = makeHealthCheck(queue)

    return { queue, isHealthy: () => isHealthy() }
}

// TODO: remove once we've migrated
export const buildAsyncIngestionConsumer = ({ hub, piscina }: { hub: Hub; piscina: Piscina }) => {
    return new KafkaJSIngestionConsumer(
        hub,
        piscina,
        KAFKA_EVENTS_JSON,
        `${KAFKA_PREFIX}clickhouse-plugin-server-async`,
        eachBatchAsyncHandlers
    )
}

export const buildOnEventIngestionConsumer = ({ hub, piscina }: { hub: Hub; piscina: Piscina }) => {
    return new KafkaJSIngestionConsumer(
        hub,
        piscina,
        KAFKA_EVENTS_JSON,
        `${KAFKA_PREFIX}clickhouse-plugin-server-async-onevent`,
        eachBatchAppsOnEventHandlers
    )
}

export const buildWebhooksIngestionConsumer = ({ hub, piscina }: { hub: Hub; piscina: Piscina }) => {
    return new KafkaJSIngestionConsumer(
        hub,
        piscina,
        KAFKA_EVENTS_JSON,
        `${KAFKA_PREFIX}clickhouse-plugin-server-async-webhooks`,
        eachBatchWebhooksHandlers
    )
}

export function makeHealthCheck(queue: KafkaJSIngestionConsumer) {
    const sessionTimeout = 30000
    const { HEARTBEAT } = queue.consumer.events
    let lastHeartbeat: number = Date.now()
    queue.consumer.on(HEARTBEAT, ({ timestamp }) => (lastHeartbeat = timestamp))

    const isHealthy = async () => {
        // Consumer has heartbeat within the session timeout, so it is healthy.
        const milliSecondsToLastHeartbeat = Date.now() - lastHeartbeat
        if (milliSecondsToLastHeartbeat < sessionTimeout) {
            status.info('👍', 'Consumer heartbeat is healthy', { milliSecondsToLastHeartbeat, sessionTimeout })
            return true
        }

        // Consumer has not heartbeat, but maybe it's because the group is
        // currently rebalancing.
        try {
            const { state } = await queue.consumer.describeGroup()

            status.info('ℹ️', 'Consumer group state', { state })

            return ['CompletingRebalance', 'PreparingRebalance'].includes(state)
        } catch (error) {
            status.error('🚨', 'Error checking consumer group state', { error })
            return false
        }
    }
    return isHealthy
}
