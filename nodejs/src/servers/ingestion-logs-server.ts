import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { CommonConfig } from '../common/config'
import { defaultConfig } from '../config/config'
import { KAFKA_APP_METRICS_2 } from '../config/kafka-topics'
import { createPosthogRedisConnectionConfig } from '../config/redis-pools'
import { APP_METRICS_OUTPUT } from '../ingestion/common/outputs'
import { DatabaseConnectionConfig, KafkaBrokerConfig, RedisConnectionsConfig } from '../ingestion/config'
import { SingleIngestionOutput } from '../ingestion/outputs/single-ingestion-output'
import { KafkaProducerWrapper } from '../kafka/producer'
import { LogsIngestionConsumerConfig } from '../logs-ingestion/config'
import { LogsIngestionConsumer } from '../logs-ingestion/logs-ingestion-consumer'
import { PluginServerService, RedisPool } from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { logger } from '../utils/logger'
import { TeamManager } from '../utils/team-manager'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Config type for a standalone logs ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - LogsIngestionConsumerConfig: Kafka topics, Redis, rate limiter settings
 * - Infrastructure configs: Kafka broker, Postgres, Redis
 * - Remaining CommonConfig picks: server mode, observability
 */
export type IngestionLogsServerConfig = BaseServerConfig &
    LogsIngestionConsumerConfig &
    KafkaBrokerConfig &
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    Pick<CommonConfig, 'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'CLOUD_DEPLOYMENT' | 'HEALTHCHECK_MAX_STALE_SECONDS'>

export class IngestionLogsServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionLogsServerConfig

    private postgres?: PostgresRouter
    private posthogRedisPool?: RedisPool
    private kafkaProducer?: KafkaProducerWrapper
    private mskProducer?: KafkaProducerWrapper

    constructor(config: Partial<IngestionLogsServerConfig> = {}) {
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
        // 1. Shared infrastructure
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK)
        this.mskProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK, 'METRICS_PRODUCER')
        logger.info('👍', 'Kafka ready')

        logger.info('🤔', 'Connecting to PostHog Redis...')
        this.posthogRedisPool = createRedisPoolFromConfig({
            connection: createPosthogRedisConnectionConfig(this.config),
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        logger.info('👍', 'PostHog Redis ready')

        const teamManager = new TeamManager(this.postgres)
        const quotaLimiting = new QuotaLimiting(this.posthogRedisPool, teamManager)

        // 2. Logs ingestion consumer
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const consumer = new LogsIngestionConsumer(this.config, {
                teamManager,
                quotaLimiting,
                kafkaProducer: this.kafkaProducer!,
                appMetricsOutput: new SingleIngestionOutput(
                    APP_METRICS_OUTPUT,
                    KAFKA_APP_METRICS_2,
                    this.mskProducer!,
                    'msk'
                ),
            })
            await consumer.start()
            return consumer.service
        })

        const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
        this.lifecycle.services.push(...readyServices)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [this.kafkaProducer, this.mskProducer].filter(Boolean) as KafkaProducerWrapper[],
            redisPools: [this.posthogRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
        }
    }
}
