import { Consumer } from 'kafkajs'
import { Message } from 'node-rdkafka'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub, PluginServerService } from '../../types'
import { status } from '../../utils/status'
import { HookCommander } from '../../worker/ingestion/hooks'
import { eachBatchAppsOnEventHandlers } from './batch-processing/each-batch-onevent'
import { eachBatchWebhooksHandlers } from './batch-processing/each-batch-webhooks'
import { IngestionConsumer } from './kafka-queue'

export const startAsyncOnEventHandlerConsumer = async ({ hub }: { hub: Hub }): Promise<PluginServerService> => {
    /*
        Consumes analytics events from the Kafka topic `clickhouse_events_json`
        and processes any onEvent plugin handlers configured for the team.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', `Starting onEvent handler consumer`)

    const consumer = new IngestionConsumer(
        hub,
        KAFKA_EVENTS_JSON,
        `${KAFKA_PREFIX}clickhouse-plugin-server-async-onevent`,
        eachBatchAppsOnEventHandlers
    )

    await hub.actionManager.start()

    const { isHealthy } = await consumer.start()

    return {
        id: 'on-event-ingestion',
        batchConsumer: consumer.consumer,
        healthcheck: isHealthy,
        onShutdown: async () => await consumer.stop(),
    }
}

export const startAsyncWebhooksHandlerConsumer = async ({ hub }: { hub: Hub }): Promise<PluginServerService> => {
    /*
        Consumes analytics events from the Kafka topic `clickhouse_events_json`
        and processes any onEvent plugin handlers configured for the team.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', `Starting webhooks handler consumer`)

    const hookCannon = new HookCommander(
        hub.postgres,
        hub.teamManager,
        hub.organizationManager,
        hub.rustyHook,
        hub.appMetrics,
        hub.EXTERNAL_REQUEST_TIMEOUT_MS
    )
    const concurrency = hub.TASKS_PER_WORKER || 20

    const batchHandler = async (payload: Message[], consumer: IngestionConsumer) => {
        const hub = consumer.pluginsServer
        if (!consumer.consumer?.consumer) {
            return // Consumer was closed
        }
        await eachBatchWebhooksHandlers(
            payload,
            consumer.consumer?.consumer,
            hub.actionMatcher,
            hookCannon,
            concurrency,
            hub.groupTypeManager,
            hub.organizationManager,
            hub.postgres
        )
    }

    const consumer = new IngestionConsumer(
        hub,
        KAFKA_EVENTS_JSON,
        `${KAFKA_PREFIX}clickhouse-plugin-server-async-webhooks`,
        batchHandler
    )

    const onShutdown = async () => {
        await hub.actionManager.stop()
        try {
            await consumer.stop()
        } catch (e) {
            status.error('🚨', 'Error stopping consumer', e)
        }
    }

    const { isHealthy } = await consumer.start()

    return {
        id: 'webhooks-ingestion',
        healthcheck: isHealthy,
        batchConsumer: consumer.consumer,
        onShutdown,
    }
}

export function makeHealthCheck(consumer: Consumer, sessionTimeout: number) {
    const { HEARTBEAT } = consumer.events
    let lastHeartbeat: number = Date.now()
    consumer.on(HEARTBEAT, ({ timestamp }) => (lastHeartbeat = timestamp))

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
            const { state } = await consumer.describeGroup()

            status.info('ℹ️', 'Consumer group state', { state })

            return ['CompletingRebalance', 'PreparingRebalance'].includes(state)
        } catch (error) {
            status.error('🚨', 'Error checking consumer group state', { error })
            return false
        }
    }
    return isHealthy
}
