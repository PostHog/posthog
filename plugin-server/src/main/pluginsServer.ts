import { ReaderModel } from '@maxmind/geoip2-node'
import Piscina from '@posthog/piscina'
import * as Sentry from '@sentry/node'
import { Server } from 'http'
import { Consumer, KafkaJSProtocolError } from 'kafkajs'
import net, { AddressInfo } from 'net'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'

import { getPluginServerCapabilities } from '../capabilities'
import { defaultConfig } from '../config/config'
import { Hub, PluginServerCapabilities, PluginsServerConfig } from '../types'
import { createHub, createKafkaClient, KafkaConfig } from '../utils/db/hub'
import { killProcess } from '../utils/kill'
import { captureEventLoopMetrics } from '../utils/metrics'
import { cancelAllScheduledJobs } from '../utils/node-schedule'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { createPostgresPool, delay, getPiscinaStats, stalenessCheck } from '../utils/utils'
import { TeamManager } from '../worker/ingestion/team-manager'
import { makePiscina as defaultMakePiscina } from '../worker/piscina'
import { GraphileWorker } from './graphile-worker/graphile-worker'
import { loadPluginSchedule } from './graphile-worker/schedule'
import { startGraphileWorker } from './graphile-worker/worker-setup'
import { startAnalyticsEventsIngestionConsumer } from './ingestion-queues/analytics-events-ingestion-consumer'
import { startAnalyticsEventsIngestionOverflowConsumer } from './ingestion-queues/analytics-events-ingestion-overflow-consumer'
import { startAnonymousEventBufferConsumer } from './ingestion-queues/anonymous-event-buffer-consumer'
import { startJobsConsumer } from './ingestion-queues/jobs-consumer'
import { IngestionConsumer } from './ingestion-queues/kafka-queue'
import { startOnEventHandlerConsumer } from './ingestion-queues/on-event-handler-consumer'
import { startScheduledTasksConsumer } from './ingestion-queues/scheduled-tasks-consumer'
import { startSessionRecordingEventsConsumer } from './ingestion-queues/session-recordings-consumer'
import { createHttpServer } from './services/http-server'
import { createMmdbServer, performMmdbStalenessCheck, prepareMmdb } from './services/mmdb'

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
    hub: Hub
    piscina: Piscina
    queue: IngestionConsumer | null
    mmdb?: ReaderModel
    mmdbUpdateJob?: schedule.Job
    stop: () => Promise<void>
}

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    makePiscina: (config: PluginsServerConfig) => Piscina = defaultMakePiscina,
    capabilities: PluginServerCapabilities | undefined
): Promise<Partial<ServerInstance>> {
    const timer = new Date()

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)
    status.info('ℹ️', `${serverConfig.WORKER_CONCURRENCY} workers, ${serverConfig.TASKS_PER_WORKER} tasks per worker`)

    // Structure containing initialized clients for Postgres, Kafka, Redis, etc.
    let hub: Hub | undefined

    // Used to trigger reloads of plugin code/config
    let pubSub: PubSub | undefined

    // A Node Worker Thread pool
    let piscina: Piscina | undefined

    // Ingestion Kafka consumer. Handles both analytics events and screen
    // recording events. The functionality roughly looks like:
    //
    // 1. events come in via the /e/ and friends endpoints and published to the
    //    plugin_events_ingestion Kafka topic.
    // 2. this queue consumes from the plugin_events_ingestion topic.
    // 3. update or creates people in the Persons table in pg with the new event
    //    data.
    // 4. passes he event through `processEvent` on any plugins that the team
    //    has enabled.
    // 5. publishes the resulting event to a Kafka topic on which ClickHouse is
    //    listening.
    let analyticsEventsIngestionConsumer: IngestionConsumer | undefined
    let analyticsEventsIngestionOverflowConsumer: IngestionConsumer | undefined

    let onEventHandlerConsumer: IngestionConsumer | undefined

    // Kafka consumer. Handles events that we couldn't find an existing person
    // to associate. The buffer handles delaying the ingestion of these events
    // (default 60 seconds) to allow for the person to be created in the
    // meantime.
    let bufferConsumer: Consumer | undefined
    let sessionRecordingEventsConsumer: Consumer | undefined
    let jobsConsumer: Consumer | undefined
    let schedulerTasksConsumer: Consumer | undefined

    let httpServer: Server | undefined // healthcheck server
    let mmdbServer: net.Server | undefined // geoip server

    let graphileWorker: GraphileWorker | undefined

    let closeHub: (() => Promise<void>) | undefined

    let lastActivityCheck: NodeJS.Timeout | undefined
    let stopEventLoopMetrics: (() => void) | undefined

    let shuttingDown = false
    async function closeJobs(): Promise<void> {
        shuttingDown = true
        status.info('💤', ' Shutting down gracefully...')
        lastActivityCheck && clearInterval(lastActivityCheck)

        // HACKY: Stop all consumers and the graphile worker, as well as the
        // http server. Note that we close the http server before the others to
        // ensure that e.g. if something goes wrong and we deadlock, then if
        // we're running in k8s, the liveness check will fail, and thus k8s will
        // kill the pod.
        //
        // I say hacky because we've got a weak dependency on the liveness check
        // configuration.
        httpServer?.close()
        cancelAllScheduledJobs()
        stopEventLoopMetrics?.()
        await Promise.allSettled([
            pubSub?.stop(),
            graphileWorker?.stop(),
            analyticsEventsIngestionConsumer?.stop(),
            analyticsEventsIngestionOverflowConsumer?.stop(),
            onEventHandlerConsumer?.stop(),
            bufferConsumer?.disconnect(),
            jobsConsumer?.disconnect(),
            sessionRecordingEventsConsumer?.disconnect(),
            schedulerTasksConsumer?.disconnect(),
        ])

        await new Promise<void>((resolve, reject) =>
            !mmdbServer
                ? resolve()
                : mmdbServer.close((error) => {
                      if (error) {
                          reject(error)
                      } else {
                          status.info('🛑', 'Closed internal MMDB server!')
                          resolve()
                      }
                  })
        )

        if (piscina) {
            await stopPiscina(piscina)
        }

        await closeHub?.()

        status.info('👋', 'Over and out!')
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, () => process.emit('beforeExit', 0))
    }

    process.on('beforeExit', async () => {
        // This makes async exit possible with the process waiting until jobs are closed
        await closeJobs()
        process.exit(0)
    })

    process.on('unhandledRejection', (error: Error) => {
        status.error('🤮', `Unhandled Promise Rejection: ${error.stack}`)

        if (error instanceof KafkaJSProtocolError) {
            kafkaProtocolErrors.inc({
                type: error.type,
                code: error.code,
            })

            // Ignore some "business as usual" Kafka errors, send the rest to sentry
            // Code list in https://kafka.apache.org/0100/protocol.html
            switch (error.code) {
                case 27: // REBALANCE_IN_PROGRESS
                    hub!.statsd?.increment(`kafka_consumer_group_rebalancing`)
                    return
                case 22: // ILLEGAL_GENERATION
                    hub!.statsd?.increment(`kafka_consumer_invalid_group_generation_id`)
                    return
            }
        }

        Sentry.captureException(error)
    })

    process.on('uncaughtException', async (error: Error) => {
        // If there are unhandled exceptions anywhere, perform a graceful
        // shutdown. The initial trigger for including this handler is due to
        // the graphile-worker code throwing an exception when it can't call
        // `nudge` on a worker. Unsure as to why this happens, but at any rate,
        // to ensure that we gracefully shutdown Kafka consumers, for which
        // unclean shutdowns can cause considerable delay in starting to consume
        // again, we try to gracefully shutdown.
        //
        // See https://nodejs.org/api/process.html#event-uncaughtexception for
        // details on the handler.
        if (shuttingDown) {
            return
        }
        status.error('🤮', `uncaught_exception`, { error: error.stack })
        await closeJobs()

        process.exit(1)
    })

    capabilities = capabilities ?? getPluginServerCapabilities(serverConfig)
    let serverInstance: (Partial<ServerInstance> & Pick<ServerInstance, 'hub'>) | undefined

    // A collection of healthchecks that should be used to validate the
    // health of the plugin-server. These are used by the /_health endpoint
    // to determine if we should trigger a restart of the pod. These should
    // be super lightweight and ideally not do any IO.
    const healthChecks: { [service: string]: () => Promise<boolean> } = {}

    try {
        if (!serverConfig.DISABLE_MMDB && capabilities.mmdb) {
            ;[hub, closeHub] = await createHub(serverConfig, null, capabilities)
            serverInstance = { hub }

            serverInstance.mmdb = (await prepareMmdb(serverInstance)) ?? undefined
            serverInstance.mmdbUpdateJob = schedule.scheduleJob('0 */4 * * *', async () =>
                serverInstance ? await performMmdbStalenessCheck(serverInstance) : null
            )
            mmdbServer = await createMmdbServer(serverInstance)
            serverConfig.INTERNAL_MMDB_SERVER_PORT = (mmdbServer.address() as AddressInfo).port
            hub.INTERNAL_MMDB_SERVER_PORT = serverConfig.INTERNAL_MMDB_SERVER_PORT
        }

        // Based on the mode the plugin server was started, we start a number of
        // different services. Mostly this is reasonably obvious from the name.
        // There is however the `queue` which is a little more complicated.
        // Depending on the capabilities we start with, it will either consume
        // from:
        //
        // 1. plugin_events_ingestion
        // 2. clickhouse_events_json
        // 3. clickhouse_events_json and plugin_events_ingestion
        // 4. conversion_events_buffer
        //
        if (capabilities.processPluginJobs || capabilities.pluginScheduledTasks) {
            ;[hub, closeHub] = hub ? [hub, closeHub] : await createHub(serverConfig, null, capabilities)
            serverInstance = serverInstance ? serverInstance : { hub }

            graphileWorker = new GraphileWorker(hub)
            // `connectProducer` just runs the PostgreSQL migrations. Ideally it
            // would be great to move the migration to bin/migrate and ensure we
            // have a way for the pods to wait for the migrations to complete as
            // we do with other migrations. However, I couldn't find a
            // `graphile-worker` supported way to do this, and I don't think
            // it's that heavy so it may be fine, but something to watch out
            // for.
            await graphileWorker.connectProducer()
            piscina = piscina ?? makePiscina(serverConfig)
            await startGraphileWorker(hub, graphileWorker, piscina)

            if (capabilities.pluginScheduledTasks) {
                schedulerTasksConsumer = await startScheduledTasksConsumer({
                    piscina: piscina,
                    kafka: hub.kafka,
                    producer: hub.kafkaProducer.producer,
                    partitionConcurrency: serverConfig.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
                    statsd: hub.statsd,
                })
            }

            if (capabilities.processPluginJobs) {
                jobsConsumer = await startJobsConsumer({
                    kafka: hub.kafka,
                    producer: hub.kafkaProducer.producer,
                    graphileWorker: graphileWorker,
                    statsd: hub.statsd,
                })
            }
        }

        if (capabilities.ingestion) {
            ;[hub, closeHub] = hub ? [hub, closeHub] : await createHub(serverConfig, null, capabilities)
            serverInstance = serverInstance ? serverInstance : { hub }

            piscina = piscina ?? makePiscina(serverConfig)
            const { queue, isHealthy: isAnalyticsEventsIngestionHealthy } = await startAnalyticsEventsIngestionConsumer(
                {
                    hub: hub,
                    piscina: piscina,
                }
            )

            analyticsEventsIngestionConsumer = queue
            healthChecks['analytics-ingestion'] = isAnalyticsEventsIngestionHealthy

            bufferConsumer = await startAnonymousEventBufferConsumer({
                hub: hub,
                piscina: piscina,
                kafka: hub.kafka,
                producer: hub.kafkaProducer,
                statsd: hub.statsd,
            })
        }

        if (capabilities.ingestionOverflow) {
            ;[hub, closeHub] = hub ? [hub, closeHub] : await createHub(serverConfig, null, capabilities)
            serverInstance = serverInstance ? serverInstance : { hub }

            piscina = piscina ?? makePiscina(serverConfig)
            analyticsEventsIngestionOverflowConsumer = await startAnalyticsEventsIngestionOverflowConsumer({
                hub: hub,
                piscina: piscina,
            })
        }

        if (capabilities.processAsyncHandlers) {
            ;[hub, closeHub] = hub ? [hub, closeHub] : await createHub(serverConfig, null, capabilities)
            serverInstance = serverInstance ? serverInstance : { hub }

            piscina = piscina ?? makePiscina(serverConfig)
            onEventHandlerConsumer = await startOnEventHandlerConsumer({
                hub: hub,
                piscina: piscina,
            })
        }

        // If we have
        if (hub && serverInstance) {
            pubSub = new PubSub(hub, {
                [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                    status.info('⚡', 'Reloading plugins!')
                    await piscina?.broadcastTask({ task: 'reloadPlugins' })

                    if (hub?.capabilities.pluginScheduledTasks && piscina) {
                        await piscina.broadcastTask({ task: 'reloadSchedule' })
                        hub.pluginSchedule = await loadPluginSchedule(piscina)
                    }
                },
                'reset-available-features-cache': async (message) => {
                    await piscina?.broadcastTask({ task: 'resetAvailableFeaturesCache', args: JSON.parse(message) })
                },
                ...(capabilities.processAsyncHandlers
                    ? {
                          'reload-action': async (message) =>
                              await piscina?.broadcastTask({ task: 'reloadAction', args: JSON.parse(message) }),
                          'drop-action': async (message) =>
                              await piscina?.broadcastTask({ task: 'dropAction', args: JSON.parse(message) }),
                      }
                    : {}),
            })

            await pubSub.start()

            // every 5 minutes all ActionManager caches are reloaded for eventual consistency
            schedule.scheduleJob('*/5 * * * *', async () => {
                await piscina?.broadcastTask({ task: 'reloadAllActions' })
            })
            // every 5 seconds set Redis keys @posthog-plugin-server/ping and @posthog-plugin-server/version
            schedule.scheduleJob('*/5 * * * * *', async () => {
                await hub!.db!.redisSet('@posthog-plugin-server/ping', new Date().toISOString(), 60, {
                    jsonSerialize: false,
                })
                await hub!.db!.redisSet('@posthog-plugin-server/version', version, undefined, { jsonSerialize: false })
            })
            // every 10 seconds sends stuff to StatsD
            schedule.scheduleJob('*/10 * * * * *', () => {
                if (piscina) {
                    for (const [key, value] of Object.entries(getPiscinaStats(piscina))) {
                        if (value !== undefined) {
                            hub!.statsd?.gauge(`piscina.${key}`, value)
                        }
                    }
                }
            })

            if (hub.statsd) {
                stopEventLoopMetrics = captureEventLoopMetrics(hub.statsd, hub.instanceId)
            }

            if (serverConfig.STALENESS_RESTART_SECONDS > 0) {
                // check every 10 sec how long it has been since the last activity

                let lastFoundActivity: number
                lastActivityCheck = setInterval(() => {
                    const stalenessCheckResult = stalenessCheck(hub, serverConfig.STALENESS_RESTART_SECONDS)

                    if (
                        hub?.lastActivity &&
                        stalenessCheckResult.isServerStale &&
                        lastFoundActivity !== hub?.lastActivity
                    ) {
                        lastFoundActivity = hub?.lastActivity
                        const extra = {
                            piscina: piscina ? JSON.stringify(getPiscinaStats(piscina)) : null,
                            ...stalenessCheckResult,
                        }
                        Sentry.captureMessage(
                            `Plugin Server has not ingested events for over ${serverConfig.STALENESS_RESTART_SECONDS} seconds! Rebooting.`,
                            {
                                extra,
                            }
                        )
                        console.log(
                            `Plugin Server has not ingested events for over ${serverConfig.STALENESS_RESTART_SECONDS} seconds! Rebooting.`,
                            extra
                        )
                        hub?.statsd?.increment(`alerts.stale_plugin_server_restarted`)

                        killProcess()
                    }
                }, Math.min(serverConfig.STALENESS_RESTART_SECONDS, 10000))
            }

            serverInstance.piscina = piscina
            serverInstance.queue = analyticsEventsIngestionConsumer
            serverInstance.stop = closeJobs

            hub.statsd?.timing('total_setup_time', timer)
            status.info('🚀', 'All systems go')

            hub.lastActivity = new Date().valueOf()
            hub.lastActivityType = 'serverStart'
        }

        if (capabilities.sessionRecordingIngestion) {
            const kafka = hub?.kafka ?? createKafkaClient(serverConfig as KafkaConfig)
            const postgres = hub?.postgres ?? createPostgresPool(serverConfig.DATABASE_URL)
            const teamManager = hub?.teamManager ?? new TeamManager(postgres, serverConfig)
            const { consumer, isHealthy: isSessionRecordingsHealthy } = await startSessionRecordingEventsConsumer({
                teamManager: teamManager,
                kafka: kafka,
                partitionsConsumedConcurrently: serverConfig.RECORDING_PARTITIONS_CONSUMED_CONCURRENTLY,
            })
            sessionRecordingEventsConsumer = consumer
            healthChecks['session-recordings'] = isSessionRecordingsHealthy
        }

        if (capabilities.http) {
            httpServer = createHttpServer(healthChecks, analyticsEventsIngestionConsumer)
        }

        return serverInstance ?? { stop: closeJobs }
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
        void Sentry.flush().catch(() => null) // Flush Sentry in the background
        await closeJobs()
        process.exit(1)
    }
}

export async function stopPiscina(piscina: Piscina): Promise<void> {
    // Wait *up to* 5 seconds to shut down VMs.
    await Promise.race([piscina.broadcastTask({ task: 'teardownPlugins' }), delay(5000)])
    // Wait 2 seconds to flush the last queues and caches
    await Promise.all([piscina.broadcastTask({ task: 'flushKafkaMessages' }), delay(2000)])
    try {
        await piscina.destroy()
    } catch {}
}

const kafkaProtocolErrors = new Counter({
    name: 'kafka_protocol_errors_total',
    help: 'Kafka protocol errors encountered, by type',
    labelNames: ['type', 'code'],
})
