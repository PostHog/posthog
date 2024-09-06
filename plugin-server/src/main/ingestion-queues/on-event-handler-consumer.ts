import { Consumer } from 'kafkajs'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub, PluginServerService } from '../../types'
import { status } from '../../utils/status'
import { HookCommander } from '../../worker/ingestion/hooks'
import { eachBatchAppsOnEventHandlers } from './batch-processing/each-batch-onevent'
import { eachBatchWebhooksHandlers } from './batch-processing/each-batch-webhooks'
import { KafkaJSIngestionConsumer, setupEventHandlers } from './kafka-queue'

export const startAsyncOnEventHandlerConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
}: {
    hub: Hub
}): Promise<PluginServerService> => {
    /*
        Consumes analytics events from the Kafka topic `clickhouse_events_json`
        and processes any onEvent plugin handlers configured for the team.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', `Starting onEvent handler consumer`)

    const queue = buildOnEventIngestionConsumer({ hub })

    await hub.actionManager.start()
    await queue.start()

    return {
        id: 'on-event-ingestion',
        healthcheck: makeHealthCheck(queue.consumer, queue.sessionTimeout),
        onShutdown: async () => await queue.stop(),
    }
}

export const startAsyncWebhooksHandlerConsumer = async (hub: Hub): Promise<PluginServerService> => {
    /*
        Consumes analytics events from the Kafka topic `clickhouse_events_json`
        and processes any onEvent plugin handlers configured for the team.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', `Starting webhooks handler consumer`)

    const consumer = hub.kafka.consumer({
        // NOTE: This should never clash with the group ID specified for the kafka engine posthog/ee/clickhouse/sql/clickhouse.py
        groupId: `${KAFKA_PREFIX}clickhouse-plugin-server-async-webhooks`,
        sessionTimeout: hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
        rebalanceTimeout: hub.KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS ?? undefined,
        readUncommitted: false,
    })
    setupEventHandlers(consumer)

    const hookCannon = new HookCommander(
        hub.postgres,
        hub.teamManager,
        hub.organizationManager,
        hub.rustyHook,
        hub.appMetrics,
        hub.EXTERNAL_REQUEST_TIMEOUT_MS
    )
    const concurrency = hub.TASKS_PER_WORKER || 20

    await hub.actionManager.start()
    await consumer.subscribe({ topic: KAFKA_EVENTS_JSON, fromBeginning: false })
    await consumer.run({
        eachBatch: (payload) =>
            eachBatchWebhooksHandlers(
                payload,
                hub.actionMatcher,
                hookCannon,
                concurrency,
                hub.groupTypeManager,
                hub.organizationManager,
                hub.postgres
            ),
    })

    const onShutdown = async () => {
        await hub.actionManager.stop()
        try {
            await consumer.stop()
        } catch (e) {
            status.error('🚨', 'Error stopping consumer', e)
        }
        try {
            await consumer.disconnect()
        } catch (e) {
            status.error('🚨', 'Error disconnecting consumer', e)
        }
    }

    return {
        id: 'webhooks-ingestion',
        healthcheck: makeHealthCheck(consumer, hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS),
        onShutdown,
    }
}

export const buildOnEventIngestionConsumer = ({ hub }: { hub: Hub }) => {
    return new KafkaJSIngestionConsumer(
        hub,
        KAFKA_EVENTS_JSON,
        `${KAFKA_PREFIX}clickhouse-plugin-server-async-onevent`,
        eachBatchAppsOnEventHandlers
    )
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
