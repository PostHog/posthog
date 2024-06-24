import * as Sentry from '@sentry/node'
import fs from 'fs'
import { Server } from 'http'
import { BatchConsumer } from 'kafka/batch-consumer'
import { CompressionCodecs, CompressionTypes, KafkaJSProtocolError } from 'kafkajs'
// @ts-expect-error no type definitions
import SnappyCodec from 'kafkajs-snappy'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'
import v8Profiler from 'v8-profiler-next'

import { getPluginServerCapabilities } from '../capabilities'
import { CdpFunctionCallbackConsumer, CdpProcessedEventsConsumer } from '../cdp/cdp-consumers'
import { defaultConfig } from '../config/config'
import { Hub, PluginServerCapabilities, PluginsServerConfig } from '../types'
import { createHub } from '../utils/db/hub'
import { cancelAllScheduledJobs } from '../utils/node-schedule'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { createRedisClient, delay } from '../utils/utils'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { DeferredPersonOverrideWorker, FlatPersonOverrideWriter } from '../worker/ingestion/person-state'
import Piscina, { makePiscina as defaultMakePiscina } from '../worker/piscina'
import { GraphileWorker } from './graphile-worker/graphile-worker'
import { loadPluginSchedule } from './graphile-worker/schedule'
import { startGraphileWorker } from './graphile-worker/worker-setup'
import { startAnalyticsEventsIngestionConsumer } from './ingestion-queues/analytics-events-ingestion-consumer'
import { startAnalyticsEventsIngestionHistoricalConsumer } from './ingestion-queues/analytics-events-ingestion-historical-consumer'
import { startAnalyticsEventsIngestionOverflowConsumer } from './ingestion-queues/analytics-events-ingestion-overflow-consumer'
import { startJobsConsumer } from './ingestion-queues/jobs-consumer'
import {
    startAsyncOnEventHandlerConsumer,
    startAsyncWebhooksHandlerConsumer,
} from './ingestion-queues/on-event-handler-consumer'
import { startScheduledTasksConsumer } from './ingestion-queues/scheduled-tasks-consumer'
import { SessionRecordingIngester } from './ingestion-queues/session-recording/session-recordings-consumer'
import { expressApp, setupCommonRoutes } from './services/http-server'

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec

const { version } = require('../../package.json')

// TODO: refactor this into a class, removing the need for many different Servers
export type ServerInstance = {
    hub: Hub
    stop: () => Promise<void>
}

const pluginServerStartupTimeMs = new Counter({
    name: 'plugin_server_startup_time_ms',
    help: 'Time taken to start the plugin server, in milliseconds',
})

export async function startPluginsServer(
    config: Partial<PluginsServerConfig>,
    makePiscina: (serverConfig: PluginsServerConfig, hub: Hub) => Promise<Piscina> = defaultMakePiscina,
    capabilitiesOverride?: PluginServerCapabilities
): Promise<ServerInstance> {
    const startTime = new Date()

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)
    status.info('ℹ️', `${serverConfig.WORKER_CONCURRENCY} workers, ${serverConfig.TASKS_PER_WORKER} tasks per worker`)
    runStartupProfiles(serverConfig)

    // A Node Worker Thread pool
    let piscina: Piscina | undefined

    // A collection of functions that should be called when the server is shutting down
    const shutdownCallbacks: (() => Promise<any>)[] = []

    let httpServer: Server | undefined // server

    let shuttingDown = false

    async function closeJobs(): Promise<void> {
        shuttingDown = true
        status.info('💤', ' Shutting down gracefully...')

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
        await Promise.allSettled([...shutdownCallbacks.map((cb) => cb())])

        if (piscina) {
            await stopPiscina(piscina)
        }

        await closeHub?.()
    }

    // If join rejects or throws, then the consumer is unhealthy and we should shut down the process.
    // Ideally we would also join all the other background tasks as well to ensure we stop the
    // server if we hit any errors and don't end up with zombie instances, but I'll leave that
    // refactoring for another time. Note that we have the liveness health checks already, so in K8s
    // cases zombies should be reaped anyway, albeit not in the most efficient way.
    function shutdownOnConsumerExit(consumer: BatchConsumer) {
        consumer.join().catch(async (error) => {
            status.error('💥', 'Unexpected task joined!', { error: error.stack ?? error })
            await closeJobs()
            process.exit(1)
        })
    }

    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, () => process.emit('beforeExit', 0))
    }

    process.on('beforeExit', async () => {
        // This makes async exit possible with the process waiting until jobs are closed
        status.info('👋', 'process handling beforeExit event. Closing jobs...')
        await closeJobs()
        status.info('👋', 'Over and out!')
        process.exit(0)
    })

    // Code list in https://kafka.apache.org/0100/protocol.html
    const kafkaJSIgnorableCodes = new Set([
        22, // ILLEGAL_GENERATION
        25, // UNKNOWN_MEMBER_ID
        27, // REBALANCE_IN_PROGRESS
    ])

    process.on('unhandledRejection', (error: Error | any, promise: Promise<any>) => {
        status.error('🤮', `Unhandled Promise Rejection`, { error, promise })

        if (error instanceof KafkaJSProtocolError) {
            kafkaProtocolErrors.inc({
                type: error.type,
                code: error.code,
            })

            // Ignore some "business as usual" Kafka errors, send the rest to sentry
            if (error.code in kafkaJSIgnorableCodes) {
                return
            }
        }

        Sentry.captureException(error, {
            extra: { detected_at: `pluginServer.ts on unhandledRejection` },
        })
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

    const capabilities = capabilitiesOverride ?? getPluginServerCapabilities(serverConfig)

    // A collection of healthchecks that should be used to validate the
    // health of the plugin-server. These are used by the /_health endpoint
    // to determine if we should trigger a restart of the pod. These should
    // be super lightweight and ideally not do any IO.
    const healthChecks: { [service: string]: () => Promise<boolean> | boolean } = {}
    const readyChecks: { [service: string]: () => Promise<boolean> | boolean } = {}

    // Creating a dedicated single-connection redis client to this Redis, as it's not relevant for hobby
    // and cloud deploys don't have concurrent uses. We should abstract multi-Redis into a router util.
    const captureRedis = serverConfig.CAPTURE_CONFIG_REDIS_HOST
        ? await createRedisClient(serverConfig.CAPTURE_CONFIG_REDIS_HOST)
        : undefined

    const [hub, closeHub] = await createHub(serverConfig, capabilities)

    const serverInstance: ServerInstance = {
        hub,
        stop: closeJobs,
    }

    try {
        const capabilitiesPromises: Promise<any>[] = []
        const startCapabilities = (
            capability: keyof PluginServerCapabilities | (keyof PluginServerCapabilities)[],
            startup: () => Promise<any> | void
        ) => {
            if (Array.isArray(capability)) {
                if (!capability.some((c) => capabilities[c])) {
                    return
                }
            } else if (!capabilities[capability]) {
                return
            }

            const start = Date.now()
            status.info('⚡️', `Starting service with capabilities ${capability}`)
            const promise = (startup() ?? Promise.resolve()).then(() =>
                status.info('🚀', `Capabilities ${capability} started in ${Date.now() - start}ms`)
            )
            capabilitiesPromises.push(promise)
        }

        status.info('🚀', 'Launching plugin server...')
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
        startCapabilities(['processPluginJobs', 'pluginScheduledTasks'], async () => {
            const graphileWorker = new GraphileWorker(hub)
            shutdownCallbacks.push(async () => graphileWorker.stop())
            // `connectProducer` just runs the PostgreSQL migrations. Ideally it
            // would be great to move the migration to bin/migrate and ensure we
            // have a way for the pods to wait for the migrations to complete as
            // we do with other migrations. However, I couldn't find a
            // `graphile-worker` supported way to do this, and I don't think
            // it's that heavy so it may be fine, but something to watch out
            // for.
            await graphileWorker.connectProducer()
            const piscina = await makePiscina(serverConfig, hub)
            status.info('👷', 'Starting graphile worker...')
            await startGraphileWorker(hub, graphileWorker, piscina)
            status.info('👷', 'Graphile worker is ready!')

            if (capabilities.pluginScheduledTasks) {
                const schedulerTasksConsumer = await startScheduledTasksConsumer({
                    piscina: piscina,
                    producer: hub.kafkaProducer,
                    kafka: hub.kafka,
                    serverConfig,
                    partitionConcurrency: serverConfig.KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY,
                })
                shutdownCallbacks.push(async () => schedulerTasksConsumer.disconnect())
            }

            if (capabilities.processPluginJobs) {
                const jobsConsumer = await startJobsConsumer({
                    kafka: hub.kafka,
                    producer: hub.kafkaProducer,
                    graphileWorker,
                    serverConfig,
                })
                shutdownCallbacks.push(async () => jobsConsumer.disconnect())
            }

            const pubSub = new PubSub(hub, {
                [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                    status.info('⚡', 'Reloading plugins!')
                    await piscina?.broadcastTask({ task: 'reloadPlugins' })

                    if (hub.capabilities.pluginScheduledTasks) {
                        await piscina.broadcastTask({ task: 'reloadSchedule' })
                        hub.pluginSchedule = await loadPluginSchedule(piscina)
                    }
                },
                'reset-available-product-features-cache': async (message) => {
                    await piscina?.broadcastTask({
                        task: 'resetAvailableProductFeaturesCache',
                        args: JSON.parse(message),
                    })
                },
                'populate-plugin-capabilities': async (message) => {
                    // We need this to be done in only once
                    if (hub.capabilities.appManagementSingleton) {
                        await piscina?.broadcastTask({
                            task: 'populatePluginCapabilities',
                            args: JSON.parse(message),
                        })
                    }
                },
            })

            await pubSub.start()
            shutdownCallbacks.push(async () => pubSub.stop())

            if (capabilities.preflightSchedules) {
                // These are used by the preflight checks in the Django app to determine if
                // the plugin-server is running.
                schedule.scheduleJob('*/5 * * * * *', async () => {
                    await hub.db.redisSet(
                        '@posthog-plugin-server/ping',
                        new Date().toISOString(),
                        'preflightSchedules',
                        60,
                        {
                            jsonSerialize: false,
                        }
                    )
                    await hub.db.redisSet('@posthog-plugin-server/version', version, 'preflightSchedules', undefined, {
                        jsonSerialize: false,
                    })
                })
            }

            // TODO: Should this only be running for this kind of capability?
            pluginServerStartupTimeMs.inc(Date.now() - startTime.valueOf())
        })

        startCapabilities('ingestion', async () => {
            const consumer = await startAnalyticsEventsIngestionConsumer({
                hub: hub,
            })

            shutdownOnConsumerExit(consumer.queue.consumer!)
            shutdownCallbacks.push(async () => consumer.queue.stop())
            healthChecks['analytics-ingestion'] = consumer.isHealthy
            readyChecks['analytics-ingestion'] = () => consumer.queue.consumerReady
        })

        startCapabilities('ingestionHistorical', async () => {
            const consumer = await startAnalyticsEventsIngestionHistoricalConsumer({
                hub: hub,
            })

            shutdownCallbacks.push(async () => consumer.queue.stop())
            shutdownOnConsumerExit(consumer.queue.consumer!)
            healthChecks['analytics-ingestion-historical'] = consumer.isHealthy
        })

        startCapabilities('ingestionOverflow', async () => {
            const queue = await startAnalyticsEventsIngestionOverflowConsumer({
                hub: hub,
            })

            shutdownCallbacks.push(async () => queue.stop())
            shutdownOnConsumerExit(queue.consumer!)
        })

        startCapabilities('processAsyncOnEventHandlers', async () => {
            const consumer = await startAsyncOnEventHandlerConsumer({
                hub: hub,
            })

            shutdownCallbacks.push(async () => consumer.queue.stop())
            healthChecks['on-event-ingestion'] = consumer.isHealthy
        })

        startCapabilities('processAsyncWebhooksHandlers', async () => {
            // TODO: Move to hub
            const groupTypeManager = new GroupTypeManager(hub.postgres, hub.teamManager, serverConfig.SITE_URL)

            const consumer = await startAsyncWebhooksHandlerConsumer({
                postgres: hub.postgres,
                kafka: hub.kafka,
                teamManager: hub.teamManager,
                organizationManager: hub.organizationManager,
                serverConfig,
                rustyHook: hub.rustyHook,
                appMetrics: hub.appMetrics,
                actionMatcher: hub.actionMatcher,
                actionManager: hub.actionManager,
                groupTypeManager: groupTypeManager,
            })

            shutdownCallbacks.push(async () => consumer.stop())
            healthChecks['webhooks-ingestion'] = consumer.isHealthy
        })

        startCapabilities('sessionRecordingBlobIngestion', async () => {
            if (!hub.objectStorage) {
                throw new Error("Can't start session recording blob ingestion without object storage")
            }
            // NOTE: We intentionally pass in the original serverConfig as the ingester uses both kafkas
            const ingester = new SessionRecordingIngester(
                serverConfig,
                hub.postgres,
                hub.objectStorage,
                false,
                captureRedis
            )
            await ingester.start()

            const batchConsumer = ingester.batchConsumer

            if (batchConsumer) {
                shutdownCallbacks.push(async () => ingester.stop())
                shutdownOnConsumerExit(batchConsumer)
                healthChecks['session-recordings-blob'] = () => ingester.isHealthy() ?? false
            }
        })

        startCapabilities('sessionRecordingBlobOverflowIngestion', async () => {
            if (!hub.objectStorage) {
                throw new Error("Can't start session recording blob ingestion without object storage")
            }
            // NOTE: We intentionally pass in the original serverConfig as the ingester uses both kafkas
            // NOTE: We don't pass captureRedis to disable overflow computation on the overflow topic
            const ingester = new SessionRecordingIngester(
                serverConfig,
                hub.postgres,
                hub.objectStorage,
                true,
                undefined
            )
            await ingester.start()

            const batchConsumer = ingester.batchConsumer

            if (batchConsumer) {
                shutdownCallbacks.push(async () => ingester.stop())
                shutdownOnConsumerExit(batchConsumer)
                healthChecks['session-recordings-blob-overflow'] = () => ingester.isHealthy() ?? false
            }
        })

        startCapabilities('cdpProcessedEvents', async () => {
            const consumer = new CdpProcessedEventsConsumer(hub)
            await consumer.start()

            shutdownOnConsumerExit(consumer.batchConsumer!)
            shutdownCallbacks.push(async () => await consumer.stop())
            healthChecks['cdp-processed-events'] = () => consumer.isHealthy() ?? false
        })

        startCapabilities('cdpFunctionCallbacks', async () => {
            const consumer = new CdpFunctionCallbackConsumer(hub)
            await consumer.start()

            shutdownOnConsumerExit(consumer.batchConsumer!)
            shutdownCallbacks.push(async () => await consumer.stop())
            healthChecks['cdp-function-callbacks'] = () => consumer.isHealthy() ?? false

            // NOTE: The function callback service is more idle so can handle http requests as well
            if (capabilities.http) {
                consumer.addApiRoutes(expressApp)
            }
        })

        startCapabilities('personOverrides', () => {
            const personOverridesPeriodicTask = new DeferredPersonOverrideWorker(
                hub.postgres,
                hub.kafkaProducer,
                new FlatPersonOverrideWriter(hub.postgres)
            ).runTask(5000)
            personOverridesPeriodicTask.promise.catch(async () => {
                status.error('⚠️', 'Person override worker task crashed! Requesting shutdown...')
                await closeJobs()
                process.exit(1)
            })

            shutdownCallbacks.push(async () => personOverridesPeriodicTask.stop())
        })

        await Promise.all(capabilitiesPromises)

        // HTTP we setup last as it is somewhat dependent on the other services
        if (capabilities.http) {
            const app = setupCommonRoutes(healthChecks, readyChecks)

            httpServer = app.listen(serverConfig.HTTP_SERVER_PORT, () => {
                status.info('🩺', `Status server listening on port ${serverConfig.HTTP_SERVER_PORT}`)
            })
        }

        status.info('🚀', `Finished Launching plugin server in ${Date.now() - startTime.valueOf()}ms `)

        return serverInstance
    } catch (error) {
        Sentry.captureException(error)
        status.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
        void Sentry.flush().catch(() => null) // Flush Sentry in the background
        status.error('💥', 'Exception while starting server, shutting down!', { error })
        await closeJobs()
        process.exit(1)
    }
}

export async function stopPiscina(piscina: Piscina): Promise<void> {
    // Wait *up to* 5 seconds to shut down VMs.
    await Promise.race([piscina.broadcastTask({ task: 'teardownPlugins' }), delay(5000)])
    // Wait 2 seconds to flush the last queues and caches
    await Promise.all([piscina.broadcastTask({ task: 'flushKafkaMessages' }), delay(2000)])
}

const kafkaProtocolErrors = new Counter({
    name: 'kafka_protocol_errors_total',
    help: 'Kafka protocol errors encountered, by type',
    labelNames: ['type', 'code'],
})

function runStartupProfiles(config: PluginsServerConfig) {
    if (config.STARTUP_PROFILE_CPU) {
        status.info('🩺', `Collecting cpu profile...`)
        v8Profiler.setGenerateType(1)
        v8Profiler.startProfiling('startup', true)
        setTimeout(() => {
            const profile = v8Profiler.stopProfiling('startup')
            fs.writeFileSync('./startup.cpuprofile', JSON.stringify(profile))
            status.info('🩺', `Wrote cpu profile to disk`)
            profile.delete()
        }, config.STARTUP_PROFILE_DURATION_SECONDS * 1000)
    }
    if (config.STARTUP_PROFILE_HEAP) {
        status.info('🩺', `Collecting heap profile...`)
        v8Profiler.startSamplingHeapProfiling(config.STARTUP_PROFILE_HEAP_INTERVAL, config.STARTUP_PROFILE_HEAP_DEPTH)
        setTimeout(() => {
            const profile = v8Profiler.stopSamplingHeapProfiling()
            fs.writeFileSync('./startup.heapprofile', JSON.stringify(profile))
            status.info('🩺', `Wrote heap profile to disk`)
        }, config.STARTUP_PROFILE_DURATION_SECONDS * 1000)
    }
}
