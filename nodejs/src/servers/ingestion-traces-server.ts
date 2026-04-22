import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { CommonConfig } from '../common/config'
import { defaultConfig, overrideConfigWithEnv } from '../config/config'
import { createPosthogRedisConnectionConfig } from '../config/redis-pools'
import {
    KafkaIngestionProducerEnvConfig,
    KafkaProducerEnvConfig,
    getDefaultKafkaIngestionProducerEnvConfig,
    getDefaultKafkaProducerEnvConfig,
} from '../ingestion/common/config'
import { APP_METRICS_OUTPUT } from '../ingestion/common/outputs'
import { DatabaseConnectionConfig, KafkaBrokerConfig, RedisConnectionsConfig } from '../ingestion/config'
import { KafkaProducerRegistry } from '../ingestion/outputs/kafka-producer-registry'
import {
    LogsIngestionConsumerConfig,
    LogsIngestionOutputsConfig,
    TracesIngestionConsumerConfig,
    getDefaultLogsIngestionOutputsConfig,
} from '../logs-ingestion/config'
import { createProducerRegistry } from '../logs-ingestion/outputs/producer-registry'
import {
    KafkaMskProducerEnvConfig,
    LogsProducerName,
    WARPSTREAM_LOGS_PRODUCER,
    getDefaultKafkaMskProducerEnvConfig,
} from '../logs-ingestion/outputs/producers'
import { createOutputsRegistry } from '../logs-ingestion/outputs/registry'
import { TracesIngestionConsumer } from '../logs-ingestion/traces-ingestion-consumer'
import { PluginServerService, RedisPool } from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { logger } from '../utils/logger'
import { TeamManager } from '../utils/team-manager'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Config type for a standalone traces ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - LogsIngestionConsumerConfig: base consumer config (traces reuses the logs consumer)
 * - TracesIngestionConsumerConfig: traces-specific Kafka topics, Redis, rate limiter settings
 * - LogsIngestionOutputsConfig: per-output topic + producer routing
 * - Producer env configs: typed env vars for the DEFAULT + MSK producers
 * - Infrastructure configs: Kafka broker, Postgres, Redis
 * - Remaining CommonConfig picks: server mode, observability
 */
export type IngestionTracesServerConfig = BaseServerConfig &
    LogsIngestionConsumerConfig &
    TracesIngestionConsumerConfig &
    LogsIngestionOutputsConfig &
    KafkaProducerEnvConfig &
    KafkaMskProducerEnvConfig &
    KafkaIngestionProducerEnvConfig &
    KafkaBrokerConfig &
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    Pick<CommonConfig, 'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'CLOUD_DEPLOYMENT' | 'HEALTHCHECK_MAX_STALE_SECONDS'>

export class IngestionTracesServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionTracesServerConfig

    private postgres?: PostgresRouter
    private posthogRedisPool?: RedisPool
    private producerRegistry?: KafkaProducerRegistry<LogsProducerName>

    constructor(config: Partial<IngestionTracesServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultKafkaProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaMskProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaIngestionProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultLogsIngestionOutputsConfig()),
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
        // 1. Shared infrastructure
        logger.info('ℹ️', 'Connecting to shared infrastructure...')

        this.postgres = new PostgresRouter(this.config)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.producerRegistry = (await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(
            this.config
        )) as KafkaProducerRegistry<LogsProducerName>
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

        // 2. Resolve outputs (topic + producer per logical name, env-controlled)
        const outputs = createOutputsRegistry().build(this.producerRegistry, this.config)

        // 3. Traces ingestion consumer
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const consumer = new TracesIngestionConsumer(this.config, {
                teamManager,
                quotaLimiting,
                kafkaProducer: this.producerRegistry!.getProducer(WARPSTREAM_LOGS_PRODUCER),
                appMetricsOutput: outputs.get(APP_METRICS_OUTPUT),
            })
            await consumer.start()
            return consumer.service
        })

        const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
        this.lifecycle.services.push(...readyServices)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.posthogRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            additionalCleanup: async () => {
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
