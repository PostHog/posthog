import { ReaderModel } from '@maxmind/geoip2-node'
import * as Sentry from '@sentry/node'
import { Server } from 'http'
import { Consumer, KafkaJSProtocolError } from 'kafkajs'
import net, { AddressInfo } from 'net'
import * as schedule from 'node-schedule'

import { defaultConfig } from '../config/config'
import { Hub, PluginServerCapabilities, PluginsServerConfig } from '../types'
import { createHub } from '../utils/db/hub'
import { killProcess } from '../utils/kill'
import { captureEventLoopMetrics } from '../utils/metrics'
import { cancelAllScheduledJobs } from '../utils/node-schedule'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { delay, logOrThrowJobQueueError, stalenessCheck } from '../utils/utils'
import { workerTasks } from '../worker/tasks'
import { loadPluginSchedule } from './graphile-worker/schedule'
import { startGraphileWorker } from './graphile-worker/worker-setup'
import { startAnonymousEventBufferConsumer } from './ingestion-queues/anonymous-event-buffer-consumer'
import { KafkaQueue } from './ingestion-queues/kafka-queue'
import { startQueues } from './ingestion-queues/queue'
import { createHttpServer } from './services/http-server'
import { createMmdbServer, performMmdbStalenessCheck, prepareMmdb } from './services/mmdb'

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
    hub: Hub
    queue: KafkaQueue | null
    mmdb?: ReaderModel
    mmdbUpdateJob?: schedule.Job
    stop: () => Promise<void>
}

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    capabilities: PluginServerCapabilities | null = null
): Promise<ServerInstance> {
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
    //
    // The queue also handles async handlers, reading from
    // clickhouse_events_json topic.
    let queue: KafkaQueue | undefined | null

    // Kafka consumer. Handles events that we couldn't find an existing person
    // to associate. The buffer handles delaying the ingestion of these events
    // (default 60 seconds) to allow for the person to be created in the
    // meantime.
    let bufferConsumer: Consumer | undefined

    let httpServer: Server | undefined // healthcheck server
    let mmdbServer: net.Server | undefined // geoip server

    let closeHub: () => Promise<void> | undefined

    let lastActivityCheck: NodeJS.Timeout | undefined
    let stopEventLoopMetrics: (() => void) | undefined

    async function closeJobs(): Promise<void> {
        status.info('💤', ' Shutting down gracefully...')
        lastActivityCheck && clearInterval(lastActivityCheck)
        cancelAllScheduledJobs()
        stopEventLoopMetrics?.()
        await queue?.stop()
        await pubSub?.stop()
        await hub?.graphileWorker.stop()
        await bufferConsumer?.disconnect()
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
        await closeHub?.()
        httpServer?.close()

        status.info('👋', 'Over and out!')
        // wait an extra second for any misc async task to finish
        await delay(1000)
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

        // Don't send some Kafka normal operation "errors" to Sentry - kafkajs handles these correctly
        if (error instanceof KafkaJSProtocolError) {
            if (error.message.includes('The group is rebalancing, so a rejoin is needed')) {
                hub!.statsd?.increment(`kafka_consumer_group_rebalancing`)
                return
            }

            if (error.message.includes('Specified group generation id is not valid')) {
                hub!.statsd?.increment(`kafka_consumer_invalid_group_generation_id`)
                return
            }
        }

        Sentry.captureException(error)
    })

    try {
        ;[hub, closeHub] = await createHub(serverConfig, null, capabilities)

        const serverInstance: Partial<ServerInstance> & Pick<ServerInstance, 'hub'> = {
            hub,
        }

        if (!serverConfig.DISABLE_MMDB) {
            serverInstance.mmdb = (await prepareMmdb(serverInstance)) ?? undefined
            serverInstance.mmdbUpdateJob = schedule.scheduleJob(
                '0 */4 * * *',
                async () => await performMmdbStalenessCheck(serverInstance)
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
        //
        if (hub.capabilities.http) {
            // start http server used for the healthcheck
            // TODO: include bufferConsumer in healthcheck
            httpServer = createHttpServer(hub!, serverInstance as ServerInstance)
        }

        if (hub.capabilities.ingestion || hub.capabilities.processPluginJobs || hub.capabilities.pluginScheduledTasks) {
            const graphileWorkerError = await startGraphileWorker(hub)
            if (graphileWorkerError instanceof Error) {
                try {
                    logOrThrowJobQueueError(hub, graphileWorkerError, `Cannot start job queue consumer!`)
                } catch {
                    killProcess()
                }
            }
        }

        if (hub.capabilities.ingestion) {
            bufferConsumer = await startAnonymousEventBufferConsumer({
                kafka: hub.kafka,
                producer: hub.kafkaProducer,
                graphileWorker: hub.graphileWorker,
                statsd: hub.statsd,
            })
        }

        const queues = await startQueues(hub)

        // `queue` refers to the ingestion queue.
        queue = queues.ingestion

        // use one extra Redis connection for pub-sub
        pubSub = new PubSub(hub, {
            [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                status.info('⚡', 'Reloading plugins!')
                await workerTasks['reloadPlugins'](hub!, {})

                if (hub?.capabilities.pluginScheduledTasks) {
                    await workerTasks['reloadSchedule'](hub, {})
                    hub.pluginSchedule = await loadPluginSchedule(hub)
                }
            },
            'reset-available-features-cache': async (message) => {
                await workerTasks['resetAvailableFeaturesCache'](hub!, JSON.parse(message))
            },
            ...(hub.capabilities.processAsyncHandlers
                ? {
                      'reload-action': async (message) => await workerTasks['reloadAction'](hub!, JSON.parse(message)),
                      'drop-action': async (message) => await workerTasks['dropAction'](hub!, JSON.parse(message)),
                  }
                : {}),
        })

        await pubSub.start()

        // every 5 minutes all ActionManager caches are reloaded for eventual consistency
        schedule.scheduleJob('*/5 * * * *', async () => {
            await workerTasks['reloadAllActions'](hub!, {})
        })
        // every 5 seconds set Redis keys @posthog-plugin-server/ping and @posthog-plugin-server/version
        schedule.scheduleJob('*/5 * * * * *', async () => {
            await hub!.db!.redisSet('@posthog-plugin-server/ping', new Date().toISOString(), 60, {
                jsonSerialize: false,
            })
            await hub!.db!.redisSet('@posthog-plugin-server/version', version, undefined, { jsonSerialize: false })
        })

        // every minute log information on kafka consumer
        if (queue) {
            schedule.scheduleJob('0 * * * * *', async () => {
                await queue?.emitConsumerGroupMetrics()
            })
        }

        // every minute flush internal metrics
        if (hub.internalMetrics) {
            schedule.scheduleJob('0 * * * * *', async () => {
                await hub!.internalMetrics?.flush()
            })
        }

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

        serverInstance.queue = queue
        serverInstance.stop = closeJobs

        hub.statsd?.timing('total_setup_time', timer)
        status.info('🚀', 'All systems go')

        hub.lastActivity = new Date().valueOf()
        hub.lastActivityType = 'serverStart'

        return serverInstance as ServerInstance
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', { stack: error.stack })
        void Sentry.flush().catch(() => null) // Flush Sentry in the background
        await closeJobs()
        process.exit(1)
    }
}
