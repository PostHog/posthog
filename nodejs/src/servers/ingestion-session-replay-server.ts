import { CommonConfig } from '../common/config'
import { defaultConfig } from '../config/config'
import { KafkaProducerWrapper } from '../kafka/producer'
import { SessionRecordingIngester, SessionRecordingIngesterConfig } from '../session-recording/consumer'
import { PostgresRouter, PostgresRouterConfig } from '../utils/db/postgres'
import { logger } from '../utils/logger'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Complete config type for a session replay ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - SessionRecordingIngesterConfig: recording consumer, S3, Redis, overflow
 * - PostgresRouterConfig: database connection
 * - Remaining CommonConfig picks: server mode, observability
 *
 * This type is the source of truth for which env vars session replay ingestion deployments need.
 */
export type IngestionSessionReplayServerConfig = BaseServerConfig &
    SessionRecordingIngesterConfig &
    PostgresRouterConfig &
    Pick<
        CommonConfig,
        'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'HEALTHCHECK_MAX_STALE_SECONDS' | 'KAFKA_HEALTHCHECK_SECONDS'
    >

export class IngestionSessionReplayServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayServerConfig

    private postgres?: PostgresRouter
    private kafkaProducer?: KafkaProducerWrapper
    private kafkaWarpStreamProducer?: KafkaProducerWrapper

    constructor(config: Partial<IngestionSessionReplayServerConfig> = {}) {
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
        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)
        logger.info('👍', 'Kafka ready')

        this.kafkaWarpStreamProducer = await KafkaProducerWrapper.create(
            this.config.KAFKA_CLIENT_RACK,
            'WARPSTREAM_PRODUCER'
        )

        const ingester = new SessionRecordingIngester(
            this.config,
            this.postgres!,
            this.kafkaProducer!,
            this.kafkaWarpStreamProducer
        )
        await ingester.start()
        this.lifecycle.services.push(ingester.service)
    }

    private getCleanupResources(): CleanupResources {
        // Note: kafkaWarpStreamProducer is intentionally excluded here because
        // SessionRecordingIngester owns its lifecycle and disconnects it in stop().
        return {
            kafkaProducers: [this.kafkaProducer].filter(Boolean) as KafkaProducerWrapper[],
            redisPools: [],
            postgres: this.postgres,
        }
    }
}
