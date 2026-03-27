import { CommonConfig, PluginServerMode } from '../common/config'
import { defaultConfig } from '../config/config'
import { KafkaProducerWrapper } from '../kafka/producer'
import { SessionRecordingIngester, SessionRecordingIngesterConfig } from '../session-recording/consumer'
import { RecordingApi } from '../session-replay/recording-api/recording-api'
import { RecordingApiConfig } from '../session-replay/recording-api/types'
import { PluginServerService } from '../types'
import { PostgresRouter, PostgresRouterConfig } from '../utils/db/postgres'
import { logger } from '../utils/logger'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Complete config type for a recordings deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - SessionRecordingIngesterConfig: recording consumer, S3, Redis, overflow
 * - RecordingApiConfig: ClickHouse, KMS, DynamoDB for the decryption API
 * - PostgresRouterConfig: database connection
 * - Remaining CommonConfig picks: server mode, observability
 *
 * This type is the source of truth for which env vars recordings deployments need.
 */
export type IngestionRecordingsServerConfig = BaseServerConfig &
    SessionRecordingIngesterConfig &
    RecordingApiConfig &
    PostgresRouterConfig &
    Pick<
        CommonConfig,
        'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'HEALTHCHECK_MAX_STALE_SECONDS' | 'KAFKA_HEALTHCHECK_SECONDS'
    >

export class IngestionRecordingsServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionRecordingsServerConfig

    private postgres?: PostgresRouter
    private kafkaProducer?: KafkaProducerWrapper

    constructor(config: Partial<IngestionRecordingsServerConfig> = {}) {
        this.config = { ...defaultConfig, ...config }
        this.lifecycle = new ServerLifecycle(this.config)
    }

    async start(): Promise<void> {
        return this.lifecycle.start(
            () => this.startServices(),
            () => this.getCleanupResources()
        )
    }

    async stop(error?: Error): Promise<void> {
        return this.lifecycle.stop(() => this.getCleanupResources(), error)
    }

    private async startServices(): Promise<void> {
        // 1. Infrastructure
        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)
        logger.info('👍', 'Kafka ready')

        // 2. Services
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        const isRecordingApi = this.config.PLUGIN_SERVER_MODE === PluginServerMode.recording_api

        if (isRecordingApi) {
            serviceLoaders.push(async () => {
                const api = new RecordingApi(this.config, this.postgres!)
                this.lifecycle.expressApp.use('/', api.router())
                await api.start()
                return api.service
            })
        } else {
            // recordings-blob-ingestion-v2 or recordings-blob-ingestion-v2-overflow
            serviceLoaders.push(async () => {
                const kafkaWarpStreamProducer = await KafkaProducerWrapper.create(
                    this.config.KAFKA_CLIENT_RACK,
                    'WARPSTREAM_PRODUCER'
                )

                const ingester = new SessionRecordingIngester(
                    this.config,
                    this.postgres!,
                    this.kafkaProducer!,
                    kafkaWarpStreamProducer
                )
                await ingester.start()
                return ingester.service
            })
        }

        const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
        this.lifecycle.services.push(...readyServices)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [this.kafkaProducer].filter(Boolean) as KafkaProducerWrapper[],
            redisPools: [],
            postgres: this.postgres,
        }
    }
}
