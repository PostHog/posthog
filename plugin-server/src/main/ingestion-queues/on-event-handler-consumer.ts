import { Consumer, Kafka } from 'kafkajs'
import * as schedule from 'node-schedule'
import { AppMetrics } from 'worker/ingestion/app-metrics'
import { RustyHook } from 'worker/rusty-hook'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub, PluginsServerConfig } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { PubSub } from '../../utils/pubsub'
import { status } from '../../utils/status'
import { ActionManager } from '../../worker/ingestion/action-manager'
import { ActionMatcher } from '../../worker/ingestion/action-matcher'
import { HookCommander } from '../../worker/ingestion/hooks'
import { OrganizationManager } from '../../worker/ingestion/organization-manager'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { eachBatchAppsOnEventHandlers } from './batch-processing/each-batch-onevent'
import { eachBatchWebhooksHandlers } from './batch-processing/each-batch-webhooks'
import { KafkaJSIngestionConsumer, setupEventHandlers } from './kafka-queue'

export const startAsyncOnEventHandlerConsumer = async ({
    hub, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
}: {
    hub: Hub
}) => {
    /*
        Consumes analytics events from the Kafka topic `clickhouse_events_json`
        and processes any onEvent plugin handlers configured for the team.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', `Starting onEvent handler consumer`)

    const queue = buildOnEventIngestionConsumer({ hub })

    await queue.start()

    const isHealthy = makeHealthCheck(queue.consumer, queue.sessionTimeout)

    return { queue, isHealthy: () => isHealthy() }
}

export const startAsyncWebhooksHandlerConsumer = async ({
    kafka, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    postgres,
    teamManager,
    organizationManager,
    serverConfig,
    rustyHook,
    appMetrics,
}: {
    kafka: Kafka
    postgres: PostgresRouter
    teamManager: TeamManager
    organizationManager: OrganizationManager
    serverConfig: PluginsServerConfig
    rustyHook: RustyHook
    appMetrics: AppMetrics
}) => {
    /*
        Consumes analytics events from the Kafka topic `clickhouse_events_json`
        and processes any onEvent plugin handlers configured for the team.

        At the moment this is just a wrapper around `IngestionConsumer`. We may
        want to further remove that abstraction in the future.
    */
    status.info('🔁', `Starting webhooks handler consumer`)

    const consumer = kafka.consumer({
        // NOTE: This should never clash with the group ID specified for the kafka engine posthog/ee/clickhouse/sql/clickhouse.py
        groupId: `${KAFKA_PREFIX}clickhouse-plugin-server-async-webhooks`,
        sessionTimeout: serverConfig.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
        rebalanceTimeout: serverConfig.KAFKA_CONSUMPTION_REBALANCE_TIMEOUT_MS ?? undefined,
        readUncommitted: false,
    })
    setupEventHandlers(consumer)

    const actionManager = new ActionManager(postgres)
    await actionManager.prepare()
    const actionMatcher = new ActionMatcher(postgres, actionManager)
    const hookCannon = new HookCommander(
        postgres,
        teamManager,
        organizationManager,
        rustyHook,
        appMetrics,
        serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS
    )
    const concurrency = serverConfig.TASKS_PER_WORKER || 20

    const pubSub = new PubSub(serverConfig, {
        'reload-action': async (message) => {
            const { actionId, teamId } = JSON.parse(message)
            await actionManager.reloadAction(teamId, actionId)
        },
        'drop-action': (message) => {
            const { actionId, teamId } = JSON.parse(message)
            actionManager.dropAction(teamId, actionId)
        },
    })

    await pubSub.start()

    // every 5 minutes all ActionManager caches are reloaded for eventual consistency
    schedule.scheduleJob('*/5 * * * *', async () => {
        await actionManager.reloadAllActions()
    })

    await consumer.subscribe({ topic: KAFKA_EVENTS_JSON, fromBeginning: false })
    await consumer.run({
        eachBatch: (payload) => eachBatchWebhooksHandlers(payload, actionMatcher, hookCannon, concurrency),
    })

    const isHealthy = makeHealthCheck(consumer, serverConfig.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS)

    return {
        stop: async () => {
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
        },
        isHealthy,
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
