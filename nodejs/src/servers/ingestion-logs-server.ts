import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { createPosthogRedisConnectionConfig } from '~/common/config/redis-pools'
import { startInternalMetricsExporterFromEnv, stopInternalMetricsExporter } from '~/common/internal-metrics-exporter'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import {
    LogsIngestionConsumerConfig,
    LogsIngestionOutputsConfig,
    getDefaultLogsIngestionOutputsConfig,
} from '~/logs/config'
import { LogsIngestionConsumer } from '~/logs/logs-ingestion-consumer'
import { createProducerRegistry } from '~/logs/outputs/producer-registry'
import {
    KafkaWarpstreamIngestionProducerEnvConfig,
    KafkaWarpstreamLogsProducerEnvConfig,
    LogsProducerName,
    getDefaultKafkaWarpstreamIngestionProducerEnvConfig,
    getDefaultKafkaWarpstreamLogsProducerEnvConfig,
} from '~/logs/outputs/producers'
import { createLogsOutputsRegistry } from '~/logs/outputs/registry'
import { SamplingRulesCache } from '~/logs/sampling/sampling-rules-cache'

import { CommonConfig } from '../common/config'
import { DatabaseConnectionConfig, KafkaBrokerConfig, RedisConnectionsConfig } from '../ingestion/config'
import { PluginServerService, RedisPool } from '../types'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Config type for a standalone logs ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - LogsIngestionConsumerConfig: Kafka topics, Redis, rate limiter settings
 * - LogsIngestionOutputsConfig: per-output topic + producer routing
 * - Producer env configs: typed env vars for the Warpstream logs + ingestion producers
 * - Infrastructure configs: Kafka broker, Postgres, Redis
 * - Remaining CommonConfig picks: server mode, observability
 */
export type IngestionLogsServerConfig = BaseServerConfig &
    LogsIngestionConsumerConfig &
    LogsIngestionOutputsConfig &
    KafkaWarpstreamLogsProducerEnvConfig &
    KafkaWarpstreamIngestionProducerEnvConfig &
    KafkaBrokerConfig &
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    Pick<CommonConfig, 'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'CLOUD_DEPLOYMENT' | 'HEALTHCHECK_MAX_STALE_SECONDS'>

export class IngestionLogsServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionLogsServerConfig

    private postgres?: PostgresRouter
    private posthogRedisPool?: RedisPool
    private producerRegistry?: KafkaProducerRegistry<LogsProducerName>

    constructor(config: Partial<IngestionLogsServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamLogsProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamIngestionProducerEnvConfig()),
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
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
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
        const samplingRulesCache = new SamplingRulesCache(this.postgres)

        // 2. Resolve outputs (topic + producer per logical name, env-controlled)
        const outputs = createLogsOutputsRegistry().build(this.producerRegistry, this.config)

        // 3. Logs ingestion consumer
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const consumer = new LogsIngestionConsumer(this.config, {
                teamManager,
                quotaLimiting,
                outputs,
                samplingRulesCache,
            })
            await consumer.start()
            return consumer.service
        })

        const readyServices = await Promise.all(serviceLoaders.map((loader) => loader()))
        this.lifecycle.services.push(...readyServices)

        // Dogfooding: also ship this process's prometheus metrics to the PostHog
        // Metrics product. No-op unless POSTHOG_INTERNAL_METRICS_TOKEN is set.
        startInternalMetricsExporterFromEnv('logs-ingestion')
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.posthogRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            additionalCleanup: async () => {
                stopInternalMetricsExporter()
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
