import * as Sentry from '@sentry/node'
import express from 'express'
import { Server } from 'http'
import { CompressionCodecs, CompressionTypes } from 'kafkajs'
import SnappyCodec from 'kafkajs-snappy'
import LZ4 from 'lz4-kafkajs'
import * as schedule from 'node-schedule'
import { Counter } from 'prom-client'

import { getPluginServerCapabilities } from './capabilities'
import { CdpApi } from './cdp/cdp-api'
import { CdpCyclotronWorkerPlugins } from './cdp/consumers/cdp-cyclotron-plugins-worker.consumer'
import { CdpCyclotronWorker, CdpCyclotronWorkerFetch } from './cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpInternalEventsConsumer } from './cdp/consumers/cdp-internal-event.consumer'
import { CdpProcessedEventsConsumer } from './cdp/consumers/cdp-processed-events.consumer'
import { defaultConfig } from './config/config'
import {
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
    KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
} from './config/kafka-topics'
import { IngestionConsumer } from './ingestion/ingestion-consumer'
import { KafkaProducerWrapper } from './kafka/producer'
import {
    startAsyncOnEventHandlerConsumer,
    startAsyncWebhooksHandlerConsumer,
} from './main/ingestion-queues/on-event-handler-consumer'
import { SessionRecordingIngester } from './main/ingestion-queues/session-recording/session-recordings-consumer'
import { DefaultBatchConsumerFactory } from './main/ingestion-queues/session-recording-v2/batch-consumer-factory'
import { SessionRecordingIngester as SessionRecordingIngesterV2 } from './main/ingestion-queues/session-recording-v2/consumer'
import { setupCommonRoutes } from './router'
import { Hub, PluginServerService, PluginsServerConfig } from './types'
import { closeHub, createHub } from './utils/db/hub'
import { PostgresRouter } from './utils/db/postgres'
import { createRedisClient } from './utils/db/redis'
import { isTestEnv } from './utils/env-utils'
import { parseJSON } from './utils/json-parse'
import { logger } from './utils/logger'
import { getObjectStorage } from './utils/object_storage'
import { shutdown as posthogShutdown } from './utils/posthog'
import { PubSub } from './utils/pubsub'
import { delay } from './utils/utils'
import { teardownPlugins } from './worker/plugins/teardown'
import { initPlugins as _initPlugins, reloadPlugins } from './worker/tasks'
import { populatePluginCapabilities } from './worker/vm/lazy'

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
        this.expressApp.use(express.json())
    }

    async start() {
        const startupTimer = new Date()
        this.setupListeners()

        const capabilities = getPluginServerCapabilities(this.config)
        const hub = (this.hub = await createHub(this.config, capabilities))

        // // Creating a dedicated single-connection redis client to this Redis, as it's not relevant for hobby
        // // and cloud deploys don't have concurrent uses. We should abstract multi-Redis into a router util.
        const captureRedis = this.config.CAPTURE_CONFIG_REDIS_HOST
            ? await createRedisClient(this.config.CAPTURE_CONFIG_REDIS_HOST)
            : undefined

        let _initPluginsPromise: Promise<void> | undefined

        const initPlugins = () => {
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
                    { topic: 'exceptions_ingestion', group_id: 'exceptions_ingestion' },
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

            if (capabilities.processAsyncOnEventHandlers) {
                serviceLoaders.push(async () => {
                    await initPlugins()
                    return startAsyncOnEventHandlerConsumer({
                        hub: hub,
                    })
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
                        batchConsumer: ingester.batchConsumer,
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
                    const batchConsumerFactory = new DefaultBatchConsumerFactory(this.config)
                    const producer = hub?.kafkaProducer ?? (await KafkaProducerWrapper.create(this.config))

                    const ingester = new SessionRecordingIngesterV2(
                        this.config,
                        false,
                        postgres,
                        batchConsumerFactory,
                        producer
                    )
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.sessionRecordingBlobIngestionV2Overflow) {
                serviceLoaders.push(async () => {
                    const postgres = hub?.postgres ?? new PostgresRouter(this.config)
                    const batchConsumerFactory = new DefaultBatchConsumerFactory(this.config)
                    const producer = hub?.kafkaProducer ?? (await KafkaProducerWrapper.create(this.config))

                    const ingester = new SessionRecordingIngesterV2(
                        this.config,
                        true,
                        postgres,
                        batchConsumerFactory,
                        producer
                    )
                    await ingester.start()
                    return ingester.service
                })
            }

            if (capabilities.cdpProcessedEvents) {
                serviceLoaders.push(async () => {
                    const consumer = new CdpProcessedEventsConsumer(hub)
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

            if (capabilities.cdpApi) {
                serviceLoaders.push(async () => {
                    await initPlugins()
                    const api = new CdpApi(hub)
                    this.expressApp.use('/', api.router())
                    return api.service
                })
            }

            if (capabilities.cdpCyclotronWorker) {
                if (!hub.CYCLOTRON_DATABASE_URL) {
                    logger.error('💥', 'Cyclotron database URL not set.')
                } else {
                    serviceLoaders.push(async () => {
                        const worker = new CdpCyclotronWorker(hub)
                        await worker.start()
                        return worker.service
                    })

                    if (process.env.EXPERIMENTAL_CDP_FETCH_WORKER) {
                        serviceLoaders.push(async () => {
                            const workerFetch = new CdpCyclotronWorkerFetch(hub)
                            await workerFetch.start()
                            return workerFetch.service
                        })
                    }
                }
            }

            if (capabilities.cdpCyclotronWorkerPlugins) {
                await initPlugins()
                if (!hub.CYCLOTRON_DATABASE_URL) {
                    logger.error('💥', 'Cyclotron database URL not set.')
                } else {
                    serviceLoaders.push(async () => {
                        const worker = new CdpCyclotronWorkerPlugins(hub)
                        await worker.start()
                        return worker.service
                    })
                }
            }

            const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
            this.services.push(...readyServices)

            this.pubsub = new PubSub(this.hub, {
                [hub.PLUGINS_RELOAD_PUBSUB_CHANNEL]: async () => {
                    logger.info('⚡', 'Reloading plugins!')
                    await reloadPlugins(hub)
                },
                'reset-available-product-features-cache': (message) => {
                    hub.organizationManager.resetAvailableProductFeaturesCache(parseJSON(message).organization_id)
                },
                'populate-plugin-capabilities': async (message) => {
                    // We need this to be done in only once
                    if (hub?.capabilities.appManagementSingleton) {
                        await populatePluginCapabilities(hub, Number(parseJSON(message).plugin_id))
                    }
                },
            })

            await this.pubsub.start()

            setupCommonRoutes(this.expressApp, this.services)

            if (!isTestEnv()) {
                // We don't run http server in test env currently
                this.httpServer = this.expressApp.listen(this.config.HTTP_SERVER_PORT, () => {
                    logger.info('🩺', `Status server listening on port ${this.config.HTTP_SERVER_PORT}`)
                })
            }

            // If join rejects or throws, then the consumer is unhealthy and we should shut down the process.
            // Ideally we would also join all the other background tasks as well to ensure we stop the
            // server if we hit any errors and don't end up with zombie instances, but I'll leave that
            // refactoring for another time. Note that we have the liveness health checks already, so in K8s
            // cases zombies should be reaped anyway, albeit not in the most efficient way.

            this.services.forEach((service) => {
                service.batchConsumer?.join().catch(async (error) => {
                    logger.error('💥', 'Unexpected task joined!', { error: error.stack ?? error })
                    await this.stop(error)
                })
            })
            pluginServerStartupTimeMs.inc(Date.now() - startupTimer.valueOf())
            logger.info('🚀', `All systems go in ${Date.now() - startupTimer.valueOf()}ms`)
        } catch (error) {
            Sentry.captureException(error)
            logger.error('💥', 'Launchpad failure!', { error: error.stack ?? error })
            void Sentry.flush().catch(() => null) // Flush Sentry in the background
            logger.error('💥', 'Exception while starting server, shutting down!', { error })
            await this.stop(error)
        }
    }

    private setupListeners() {
        for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
            process.on(signal, async () => {
                // This makes async exit possible with the process waiting until jobs are closed
                logger.info('👋', `process handling ${signal} event. Stopping...`)
                await this.stop()
            })
        }

        process.on('unhandledRejection', (error: Error | any, promise: Promise<any>) => {
            logger.error('🤮', `Unhandled Promise Rejection`, { error: String(error), promise })

            Sentry.captureException(error, {
                extra: { detected_at: `pluginServer.ts on unhandledRejection` },
            })
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

        logger.info('💤', ' Shutting down gracefully...')

        this.httpServer?.close()
        Object.values(schedule.scheduledJobs).forEach((job) => {
            job.cancel()
        })

        await Promise.allSettled([this.pubsub?.stop(), ...this.services.map((s) => s.onShutdown()), posthogShutdown()])

        if (this.hub) {
            // Wait *up to* 5 seconds to shut down VMs.
            await Promise.race([teardownPlugins(this.hub), delay(5000)])

            // Wait 2 seconds to flush the last queues and caches
            await Promise.all([this.hub?.kafkaProducer.flush(), delay(2000)])
            await closeHub(this.hub)
        }

        process.exit(error ? 1 : 0)
    }
}
