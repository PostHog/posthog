import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { Kafka } from 'kafkajs'
import * as schedule from 'node-schedule'
import { Pool } from 'pg'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../../config/kafka-topics'
import { Hub, PluginsServerConfig } from '../../types'
import { status } from '../../utils/status'
import { ActionManager } from '../../worker/ingestion/action-manager'
import { ActionMatcher } from '../../worker/ingestion/action-matcher'
import { HookCommander } from '../../worker/ingestion/hooks'
import { OrganizationManager } from '../../worker/ingestion/organization-manager'
import { TeamManager } from '../../worker/ingestion/team-manager'
import Piscina from '../../worker/piscina'
import {
    eachBatchAppsOnEventHandlers,
    eachBatchAsyncHandlers,
    eachBatchWebhooksHandlers,
    eachMessageWebhooksHandlers,
} from './batch-processing/each-batch-async-handlers'
import { KafkaJSIngestionConsumer, setupEventHandlers } from './kafka-queue'

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
    kafka, // TODO: remove needing to pass in the whole hub and be more selective on dependency injection.
    postgres,
    serverConfig,
}: {
    kafka: Kafka
    postgres: Pool
    serverConfig: PluginsServerConfig
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

    const consumer = kafka.consumer({
        // NOTE: This should never clash with the group ID specified for the kafka engine posthog/ee/clickhouse/sql/clickhouse.py
        groupId: `${KAFKA_PREFIX}clickhouse-plugin-server-async-webhooks`,
        sessionTimeout: 30000,
        readUncommitted: false,
    })
    setupEventHandlers(consumer)

    let statsd: StatsD | undefined
    if (serverConfig.STATSD_HOST) {
        status.info('🤔', `Connecting to StatsD...`)
        statsd = new StatsD({
            port: serverConfig.STATSD_PORT,
            host: serverConfig.STATSD_HOST,
            prefix: serverConfig.STATSD_PREFIX,
            telegraf: true,
            globalTags: serverConfig.PLUGIN_SERVER_MODE
                ? { pluginServerMode: serverConfig.PLUGIN_SERVER_MODE }
                : undefined,
            errorHandler: (error) => {
                status.warn('⚠️', 'StatsD error', error)
                Sentry.captureException(error)
            },
        })
        status.info('👍', `StatsD ready`)
    }

    const teamManager = new TeamManager(postgres, serverConfig, statsd)
    const organizationManager = new OrganizationManager(postgres, teamManager)
    const actionManager = new ActionManager(postgres)
    const actionMatcher = new ActionMatcher(postgres, actionManager, statsd)
    const hookCannon = new HookCommander(postgres, teamManager, organizationManager, statsd)
    const concurrency = 20

    await consumer.subscribe({ topic: KAFKA_EVENTS_JSON, fromBeginning: false })
    await consumer.run({
        eachBatch: (payload) =>
            eachBatchWebhooksHandlers(
                payload,
                (message) => eachMessageWebhooksHandlers(message, actionMatcher, hookCannon, statsd),
                statsd,
                concurrency
            ),
    })
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

export function makeHealthCheck(queue: KafkaJSIngestionConsumer) {
    const sessionTimeout = queue.sessionTimeout
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
