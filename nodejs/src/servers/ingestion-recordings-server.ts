import { CommonConfig, PluginServerMode } from '../common/config'
import { defaultConfig } from '../config/config'
import { KafkaProducerWrapper } from '../kafka/producer'
import { SessionRecordingIngester, SessionRecordingIngesterConfig } from '../session-recording/consumer'
import { RecordingApi } from '../session-replay/recording-api/recording-api'
import { RecordingApiConfig } from '../session-replay/recording-api/types'
import { PostgresRouter, PostgresRouterConfig } from '../utils/db/postgres'
import { stringToBoolean } from '../utils/env-utils'
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
export type IngestionRecordingsServerOwnConfig = {
    /** When true, mount the recording API alongside blob ingestion (hobby/local dev) */
    RECORDINGS_ENABLE_API: boolean
}

export type IngestionRecordingsServerConfig = BaseServerConfig &
    SessionRecordingIngesterConfig &
    RecordingApiConfig &
    PostgresRouterConfig &
    IngestionRecordingsServerOwnConfig &
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
        this.config = {
            ...defaultConfig,
            RECORDINGS_ENABLE_API: stringToBoolean(process.env.RECORDINGS_ENABLE_API ?? 'false'),
            ...config,
        }
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

        // 2. Services
        const isRecordingApiMode = this.config.PLUGIN_SERVER_MODE === PluginServerMode.recording_api
        const enableApi = isRecordingApiMode || this.config.RECORDINGS_ENABLE_API

        if (enableApi) {
            const api = new RecordingApi(this.config, this.postgres!)
            this.lifecycle.expressApp.use('/', api.router())
            await api.start()
            this.lifecycle.services.push(api.service)
        }

        if (!isRecordingApiMode) {
            // recordings-blob-ingestion-v2 or recordings-blob-ingestion-v2-overflow
            logger.info('🤔', 'Connecting to Kafka...')
            this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)
            logger.info('👍', 'Kafka ready')

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
            this.lifecycle.services.push(ingester.service)
        }
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [this.kafkaProducer].filter(Boolean) as KafkaProducerWrapper[],
            redisPools: [],
            postgres: this.postgres,
        }
    }
}
