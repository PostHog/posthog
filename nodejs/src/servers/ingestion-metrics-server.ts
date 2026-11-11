import { CommonConfig } from '@posthog/node-common/config'
import {
    DatabaseConnectionConfig,
    KafkaBrokerConfig,
    RedisConnectionsConfig,
} from '@posthog/node-common/config/connections'
import { createPosthogRedisConnectionConfig } from '@posthog/node-common/config/redis-pools'
import { KafkaProducerRegistry } from '@posthog/node-common/outputs/kafka-producer-registry'
import {
    BaseServerConfig,
    CleanupResources,
    NodeServer,
    ServerLifecycle,
} from '@posthog/node-common/servers/base-server'
import { QuotaLimiting } from '@posthog/node-common/services/quota-limiting.service'
import {
    UsageIngestionConfig,
    createUsageIngestionClient,
    usageReportTeamMatcher,
} from '@posthog/node-common/usage-ingestion/index'
import { UsageRecordBatch } from '@posthog/node-common/usage-ingestion/usage-record-batch'
import { PostgresRouter } from '@posthog/node-common/utils/db/postgres'
import { createRedisPoolFromConfig } from '@posthog/node-common/utils/db/redis'
import { logger } from '@posthog/node-common/utils/logger'
import { TeamManager } from '@posthog/node-common/utils/team-manager'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import {
    MetricsIngestionConsumerConfig,
    MetricsIngestionOutputsConfig,
    getDefaultMetricsIngestionConsumerConfig,
    getDefaultMetricsIngestionOutputsConfig,
} from '~/metrics/config'
import { MetricsPipelineConsumer } from '~/metrics/metrics-pipeline-consumer'
import { createProducerRegistry } from '~/metrics/outputs/producer-registry'
import {
    KafkaWarpstreamIngestionProducerEnvConfig,
    KafkaWarpstreamMetricsProducerEnvConfig,
    MetricsProducerName,
    getDefaultKafkaWarpstreamIngestionProducerEnvConfig,
    getDefaultKafkaWarpstreamMetricsProducerEnvConfig,
} from '~/metrics/outputs/producers'
import { createMetricsOutputsRegistry } from '~/metrics/outputs/registry'

import { PluginServerService, RedisPool } from '../types'

/**
 * Config type for a standalone Metrics ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - MetricsIngestionConsumerConfig: Kafka topics, Redis, rate limiter settings
 * - MetricsIngestionOutputsConfig: per-output topic + producer routing
 * - Producer env configs: typed env vars for the Warpstream metrics + ingestion producers
 * - Infrastructure configs: Kafka broker, Postgres, Redis
 * - Remaining CommonConfig picks: server mode, observability
 */
export type IngestionMetricsServerConfig = BaseServerConfig &
    MetricsIngestionConsumerConfig &
    MetricsIngestionOutputsConfig &
    KafkaWarpstreamMetricsProducerEnvConfig &
    KafkaWarpstreamIngestionProducerEnvConfig &
    KafkaBrokerConfig &
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    UsageIngestionConfig &
    Pick<CommonConfig, 'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'CLOUD_DEPLOYMENT' | 'HEALTHCHECK_MAX_STALE_SECONDS'>

export class IngestionMetricsServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionMetricsServerConfig

    private postgres?: PostgresRouter
    private posthogRedisPool?: RedisPool
    private producerRegistry?: KafkaProducerRegistry<MetricsProducerName>

    constructor(config: Partial<IngestionMetricsServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultMetricsIngestionConsumerConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamMetricsProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamIngestionProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultMetricsIngestionOutputsConfig()),
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

        // 2. Resolve outputs (topic + producer per logical name, env-controlled)
        const outputs = createMetricsOutputsRegistry().build(this.producerRegistry, this.config)

        // 3. Metrics ingestion consumer
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const usageBatch = new UsageRecordBatch(createUsageIngestionClient(this.config, 'metrics'), {
                unit: 'bytes',
                isTeamEnabled: usageReportTeamMatcher(this.config),
            })
            const consumer = new MetricsPipelineConsumer(this.config, {
                teamManager,
                quotaLimiting,
                outputs,
                usageBatch,
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
