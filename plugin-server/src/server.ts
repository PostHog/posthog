import express from 'express'
import { Server } from 'http'
import { CompressionCodecs, CompressionTypes } from 'kafkajs'
import SnappyCodec from 'kafkajs-snappy'
import LZ4 from 'lz4-kafkajs'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'

import { getPluginServerCapabilities } from './capabilities'
import { CdpApi } from './cdp/cdp-api'
import { CdpCyclotronWorker } from './cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp/consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpCyclotronWorkerPlugins } from './cdp/consumers/cdp-cyclotron-worker-plugins.consumer'
import { CdpCyclotronWorkerSegment } from './cdp/consumers/cdp-cyclotron-worker-segment.consumer'
import { CdpEventsConsumer } from './cdp/consumers/cdp-events.consumer'
import { CdpInternalEventsConsumer } from './cdp/consumers/cdp-internal-event.consumer'
import { CdpLegacyEventsConsumer } from './cdp/consumers/cdp-legacy-event.consumer'
import { defaultConfig } from './config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from './config/kafka-topics'
import { IngestionConsumer } from './ingestion/ingestion-consumer'
import { KafkaProducerWrapper } from './kafka/producer'
import { startAsyncWebhooksHandlerConsumer } from './main/ingestion-queues/on-event-handler-consumer'
import { SessionRecordingIngester } from './main/ingestion-queues/session-recording/session-recordings-consumer'
import { SessionRecordingIngester as SessionRecordingIngesterV2 } from './main/ingestion-queues/session-recording-v2/consumer'
import { setupCommonRoutes } from './router'
import { Hub, PluginServerService, PluginsServerConfig } from './types'
import { ServerCommands } from './utils/commands'
import { closeHub, createHub } from './utils/db/hub'
import { PostgresRouter } from './utils/db/postgres'
import { createRedisClient } from './utils/db/redis'
import { isTestEnv } from './utils/env-utils'
import { logger } from './utils/logger'
import { NodeInstrumentation } from './utils/node-instrumentation'
import { getObjectStorage } from './utils/object_storage'
import { captureException, shutdown as posthogShutdown } from './utils/posthog'
import { PubSub } from './utils/pubsub'
import { delay } from './utils/utils'
import { teardownPlugins } from './worker/plugins/teardown'
import { initPlugins as _initPlugins } from './worker/tasks'

CompressionCodecs[CompressionTypes.Snappy] = SnappyCodec
CompressionCodecs[CompressionTypes.LZ4] = new LZ4().codec

const pluginServerStartupTimeMs = new Counter({
    name: 'plugin_server_startup_time_ms',
    help: 'Time taken to start the plugin server, in milliseconds',
})

export class PluginServer {
    config: PluginsServerConfig
    pubsub?: PubSub
    services: PluginServerService[] = []
    httpServer?: Server
    stopping = false
    hub?: Hub
    expressApp: express.Application
    nodeInstrumentation: NodeInstrumentation

    constructor(
        config: Partial<PluginsServerConfig> = {},
        private options: {
            disableHttpServer?: boolean
        } = {}
    ) {
        this.config = {
            ...defaultConfig,
            ...config,
        }

        this.expressApp = express()
        this.expressApp.use(express.json({ limit: '200kb' }))
        this.nodeInstrumentation = new NodeInstrumentation(this.config)
    }

    async start(): Promise<void> {
        const startupTimer = new Date()
        this.setupListeners()
        this.nodeInstrumentation.setupThreadPerformanceInterval()

        const capabilities = getPluginServerCapabilities(this.config)
        const hub = (this.hub = await createHub(this.config, capabilities))

        // // Creating a dedicated single-connection redis client to this Redis, as it's not relevant for hobby
        // // and cloud deploys don't have concurrent uses. We should abstract multi-Redis into a router util.
        const captureRedis = this.config.CAPTURE_CONFIG_REDIS_HOST
            ? await createRedisClient(this.config.CAPTURE_CONFIG_REDIS_HOST)
            : undefined

        let _initPluginsPromise: Promise<void> | undefined

        const initPlugins = (): Promise<void> => {
            if (!_initPluginsPromise) {
                _initPluginsPromise = _initPlugins(hub)
            }

            return _initPluginsPromise
        }

        try {
            const serviceLoaders: (() => Promise<PluginServerService>)[] = []

            if (capabilities.ingestionV2Combined) {
                // NOTE: This is for single process deployments like local dev and hobby - it runs all possible consumers
                // in a single process. In production these are each separate Deployments of the standard ingestion consumer
                const consumersOptions = [
                    {
                        topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                        group_id: `clickhouse-ingestion`,
                    },
                    {
                        topic: KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
                        group_id: `clickhouse-ingestion-historical`,
                    },
                    { topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW, group_id: 'clickhouse-ingestion-overflow' },
                    { topic: 'client_iwarnings_ingestion', group_id: 'client_iwarnings_ingestion' },
                    { topic: 'heatmaps_ingestion', group_id: 'heatmaps_ingestion' },
                ]

                for (const consumerOption of consumersOptions) {
                    serviceLoaders.push(async () => {
                        await initPlugins()
                        const consumer = new IngestionConsumer(hub, {
                            INGESTION_CONSUMER_CONSUME_TOPIC: consumerOption.topic,
                            INGESTION_CONSUMER_GROUP_ID: consumerOption.group_id,
                        })
                        await consumer.start()
                        return consumer.service
                    })
                }
            } else if (capabilities.ingestionV2) {
                serviceLoaders.push(async () => {
                    await initPlugins()
                    const consumer = new IngestionConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.processAsyncWebhooksHandlers) {
                serviceLoaders.push(() => startAsyncWebhooksHandlerConsumer(hub))
            }

            if (capabilities.sessionRecordingBlobIngestion) {
                serviceLoaders.push(async () => {
                    const postgres = hub?.postgres ?? new PostgresRouter(this.config)
                    const s3 = hub?.objectStorage ?? getObjectStorage(this.config)

                    if (!s3) {
                        throw new Error("Can't start session recording blob ingestion without object storage")
                    }
                    // NOTE: We intentionally pass in the original this.config as the ingester uses both kafkas
                    const ingester = new SessionRecordingIngester(this.config, postgres, s3, false, captureRedis)
                    await ingester.start()

                    return {
                        id: 'session-recordings-blob',
                        onShutdown: async () => await ingester.stop(),
                        healthcheck: () => ingester.isHealthy() ?? false,
                    }
                })
            }

            if (capabilities.sessionRecordingBlobOverflowIngestion) {
                serviceLoaders.push(async () => {
                    const postgres = hub?.postgres ?? new PostgresRouter(this.config)
                    const s3 = hub?.objectStorage ?? getObjectStorage(this.config)

                    if (!s3) {
                        throw new Error("Can't start session recording blob ingestion without object storage")
                    }
                    // NOTE: We intentionally pass in the original this.config as the ingester uses both kafkas
                    // NOTE: We don't pass captureRedis to disable overflow computation on the overflow topic
                    const ingester = new SessionRecordingIngester(this.config, postgres, s3, true, undefined)
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.sessionRecordingBlobIngestionV2) {
                serviceLoaders.push(async () => {
                    const postgres = hub?.postgres ?? new PostgresRouter(this.config)
                    const producer = hub?.kafkaProducer ?? (await KafkaProducerWrapper.create(this.config))

                    const ingester = new SessionRecordingIngesterV2(this.config, false, postgres, producer)
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.sessionRecordingBlobIngestionV2Overflow) {
                serviceLoaders.push(async () => {
                    const postgres = hub?.postgres ?? new PostgresRouter(this.config)
                    const producer = hub?.kafkaProducer ?? (await KafkaProducerWrapper.create(this.config))

                    const ingester = new SessionRecordingIngesterV2(this.config, true, postgres, producer)
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.cdpProcessedEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpEventsConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpInternalEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpInternalEventsConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpLegacyOnEvent) {
                serviceLoaders.push(async () => {
                    await initPlugins()
                    const consumer = new CdpLegacyEventsConsumer(hub)
                    await consumer.start()
                    return consumer.service
                })
            }

            if (capabilities.cdpApi) {
                serviceLoaders.push(async () => {
                    await initPlugins()
                    const api = new CdpApi(hub)
                    this.expressApp.use('/', api.router())
                    await api.start()
                    return api.service
                })
            }

            if (capabilities.cdpCyclotronWorker) {
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorker(hub)
                    await worker.start()
                    return worker.service
                })
            }

            if (capabilities.cdpCyclotronWorkerPlugins) {
                await initPlugins()
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorkerPlugins(hub)
                    await worker.start()
                    return worker.service
                })
            }

            if (capabilities.cdpCyclotronWorkerHogFlow) {
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorkerHogFlow(hub)
                    await worker.start()
                    return worker.service
                })
            }

            // The service commands is always created
            serviceLoaders.push(async () => {
                const serverCommands = new ServerCommands(hub)
                this.expressApp.use('/', serverCommands.router())
                await serverCommands.start()
                return serverCommands.service
            })

            if (capabilities.cdpCyclotronWorkerSegment) {
                serviceLoaders.push(async () => {
                    const worker = new CdpCyclotronWorkerSegment(hub)
                    await worker.start()
                    return worker.service
                })
            }

            const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
            this.services.push(...readyServices)

            setupCommonRoutes(this.expressApp, this.services)

            if (!isTestEnv()) {
                // We don't run http server in test env currently
                this.httpServer = this.expressApp.listen(this.config.HTTP_SERVER_PORT, () => {
                    logger.info('🩺', `Status server listening on port ${this.config.HTTP_SERVER_PORT}`)
                })
            }

            pluginServerStartupTimeMs.inc(Date.now() - startupTimer.valueOf())
            logger.info('🚀', `All systems go in ${Date.now() - startupTimer.valueOf()}ms`)
        } catch (error) {
            captureException(error)
            logger.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
            logger.error('💥', 'Exception while starting server, shutting down!', { error })
            await this.stop(error)
        }
    }

    private setupListeners(): void {
        for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
            process.on(signal, async () => {
                // This makes async exit possible with the process waiting until jobs are closed
                logger.info('👋', `process handling ${signal} event. Stopping...`)
                await this.stop()
            })
        }

        process.on('unhandledRejection', (error: Error | any) => {
            logger.error('🤮', `Unhandled Promise Rejection`, { error: String(error) })

            captureException(error, {
                extra: { detected_at: `pluginServer.ts on unhandledRejection` },
            })

            void this.stop(error)
        })

        process.on('uncaughtException', async (error: Error) => {
            await this.stop(error)
        })
    }

    async stop(error?: Error): Promise<void> {
        if (error) {
            logger.error('🤮', `Shutting down due to error`, { error: error.stack })
        }
        if (this.stopping) {
            logger.info('🚨', 'Stop called but already stopping...')
            return
        }

        this.stopping = true

        this.nodeInstrumentation.cleanup()

        logger.info('💤', ' Shutting down gracefully...')

        this.httpServer?.close()
        Object.values(schedule.scheduledJobs).forEach((job) => {
            job.cancel()
        })

        logger.info('💤', ' Shutting down services...')
        await Promise.allSettled([this.pubsub?.stop(), ...this.services.map((s) => s.onShutdown()), posthogShutdown()])

        if (this.hub) {
            logger.info('💤', ' Shutting down plugins...')
            // Wait *up to* 5 seconds to shut down VMs.
            await Promise.race([teardownPlugins(this.hub), delay(5000)])

            logger.info('💤', ' Shutting down kafka producer...')
            // Wait 2 seconds to flush the last queues and caches
            await Promise.all([this.hub?.kafkaProducer.flush(), delay(2000)])
            await closeHub(this.hub)
        }

        logger.info('💤', ' Shutting down completed. Exiting...')

        process.exit(error ? 1 : 0)
    }
}
