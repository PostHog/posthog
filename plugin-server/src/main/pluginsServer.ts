import { ReaderModel } from '@maxmind/geoip2-node'
import Piscina from '@posthog/piscina'
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
import { delay, getPiscinaStats, logOrThrowJobQueueError, stalenessCheck } from '../utils/utils'
import { makePiscina as defaultMakePiscina } from '../worker/piscina'
import { loadPluginSchedule } from './graphile-worker/schedule'
import { startGraphileWorker } from './graphile-worker/worker-setup'
import { startAnonymousEventBufferConsumer } from './ingestion-queues/anonymous-event-buffer-consumer'
import { startJobsConsumer } from './ingestion-queues/jobs-consumer'
import { KafkaQueue } from './ingestion-queues/kafka-queue'
import { startQueues } from './ingestion-queues/queue'
import { createHttpServer } from './services/http-server'
import { createMmdbServer, performMmdbStalenessCheck, prepareMmdb } from './services/mmdb'

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
    hub: Hub
    piscina: Piscina
    queue: KafkaQueue | null
    mmdb?: ReaderModel
    mmdbUpdateJob?: schedule.Job
    stop: () => Promise<void>
}

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    makePiscina: (config: PluginsServerConfig) => Piscina = defaultMakePiscina,
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
    //
    // The queue also handles async handlers, reading from
    // clickhouse_events_json topic.
    let queue: KafkaQueue | undefined | null

    // Kafka consumer. Handles events that we couldn't find an existing person
    // to associate. The buffer handles delaying the ingestion of these events
    // (default 60 seconds) to allow for the person to be created in the
    // meantime.
    let bufferConsumer: Consumer | undefined
    let jobsConsumer: Consumer | undefined

    let httpServer: Server | undefined // healthcheck server
    let mmdbServer: net.Server | undefined // geoip server

    let closeHub: () => Promise<void> | undefined

    let lastActivityCheck: NodeJS.Timeout | undefined
    let stopEventLoopMetrics: (() => void) | undefined

    let shuttingDown = false
    async function closeJobs(): Promise<void> {
        shuttingDown = true
        status.info('💤', ' Shutting down gracefully...')
        lastActivityCheck && clearInterval(lastActivityCheck)
        cancelAllScheduledJobs()
        stopEventLoopMetrics?.()
        await Promise.allSettled([
            queue?.stop(),
            pubSub?.stop(),
            hub?.graphileWorker.stop(),
            bufferConsumer?.disconnect(),
            jobsConsumer?.disconnect(),
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

        piscina = makePiscina(serverConfig)

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
        if (hub.capabilities.http) {
            // start http server used for the healthcheck
            // TODO: include bufferConsumer in healthcheck
            httpServer = createHttpServer(hub!, serverInstance as ServerInstance)
        }

        if (hub.capabilities.processPluginJobs || hub.capabilities.pluginScheduledTasks) {
            const graphileWorkerError = await startGraphileWorker(hub, piscina)
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
                hub: hub,
                piscina: piscina,
                kafka: hub.kafka,
                producer: hub.kafkaProducer,
                statsd: hub.statsd,
            })
        }

        if (hub.capabilities.processPluginJobs) {
            jobsConsumer = await startJobsConsumer({
                kafka: hub.kafka,
                producer: hub.kafkaProducer.producer,
                graphileWorker: hub.graphileWorker,
                statsd: hub.statsd,
            })
        }

        const queues = await startQueues(hub, piscina)

        // `queue` refers to the ingestion queue.
        queue = queues.ingestion

        piscina.on('drain', () => {
            void hub?.graphileWorker.resumeConsumer()
        })

        // use one extra Redis connection for pub-sub
        pubSub = new PubSub(hub, {
            [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                status.info('⚡', 'Reloading plugins!')
                await piscina?.broadcastTask({ task: 'reloadPlugins' })

                if (hub?.capabilities.pluginScheduledTasks && piscina) {
                    await piscina.broadcastTask({ task: 'reloadSchedule' })
                    hub.pluginSchedule = await loadPluginSchedule(piscina)
                }
            },
            ['reload-actions']: async () => {
                status.info('⚡', 'Reloading actions!')
                await piscina?.broadcastTask({ task: 'reloadAllActions' })
            },
            'reset-available-features-cache': async (message) => {
                await piscina?.broadcastTask({ task: 'resetAvailableFeaturesCache', args: JSON.parse(message) })
            },
            ...(hub.capabilities.processAsyncHandlers
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

        // every minute log information on kafka consumer
        if (queue) {
            schedule.scheduleJob('0 * * * * *', async () => {
                await queue?.emitConsumerGroupMetrics()
            })
        }

        // every minute flush internal metrics
        if (hub.internalMetrics) {
            schedule.scheduleJob('0 * * * * *', async () => {
                await hub!.internalMetrics?.flush(piscina!)
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
        serverInstance.queue = queue
        serverInstance.stop = closeJobs

        hub.statsd?.timing('total_setup_time', timer)
        status.info('🚀', 'All systems go')

        hub.lastActivity = new Date().valueOf()
        hub.lastActivityType = 'serverStart'

        return serverInstance as ServerInstance
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', error)
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
