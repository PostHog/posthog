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
    LogsIngestionConsumerConfig,
    LogsIngestionOutputsConfig,
    TracesIngestionConsumerConfig,
    getDefaultLogsIngestionOutputsConfig,
} from '~/logs/config'
import { createTracesIngestionConsumer } from '~/logs/framework/create-consumer'
import { MetricRulesCache } from '~/logs/metrics-rules/metric-rules-cache'
import { LogsMetricsEmitter } from '~/logs/metrics-rules/metrics-emitter'
import { createProducerRegistry } from '~/logs/outputs/producer-registry'
import {
    KafkaWarpstreamIngestionProducerEnvConfig,
    KafkaWarpstreamLogsProducerEnvConfig,
    LogsProducerName,
    getDefaultKafkaWarpstreamIngestionProducerEnvConfig,
    getDefaultKafkaWarpstreamLogsProducerEnvConfig,
} from '~/logs/outputs/producers'
import { createTracesOutputsRegistry } from '~/logs/outputs/registry'
import { RetentionRulesCache } from '~/logs/retention/retention-rules-cache'
import { TracingConfigCache } from '~/logs/retention/tracing-config-cache'

import { PluginServerService, RedisPool } from '../types'

/**
 * Config type for a standalone traces ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - LogsIngestionConsumerConfig: base consumer config (traces reuses the logs consumer)
 * - TracesIngestionConsumerConfig: traces-specific Kafka topics, Redis, rate limiter settings
 * - LogsIngestionOutputsConfig: per-output topic + producer routing
 * - Producer env configs: typed env vars for the Warpstream logs + ingestion producers
 * - Infrastructure configs: Kafka broker, Postgres, Redis
 * - Remaining CommonConfig picks: server mode, observability
 */
export type IngestionTracesServerConfig = BaseServerConfig &
    LogsIngestionConsumerConfig &
    TracesIngestionConsumerConfig &
    LogsIngestionOutputsConfig &
    KafkaWarpstreamLogsProducerEnvConfig &
    KafkaWarpstreamIngestionProducerEnvConfig &
    KafkaBrokerConfig &
    DatabaseConnectionConfig &
    RedisConnectionsConfig &
    UsageIngestionConfig &
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

        // Span-based metric rules share the log rules table + OTLP emitter; the traces
        // consumer filters to `source=spans`. Inert without a traces export URL.
        const metricRulesCache = this.config.TRACES_METRICS_RULES_EXPORT_URL
            ? new MetricRulesCache(this.postgres)
            : undefined
        const metricsEmitter = this.config.TRACES_METRICS_RULES_EXPORT_URL
            ? new LogsMetricsEmitter(this.config.TRACES_METRICS_RULES_EXPORT_URL)
            : undefined

        // The tracing config supplies the per-team default for spans no rule matches.
        const retentionRulesCache = new RetentionRulesCache(this.postgres)
        const tracingConfigCache = new TracingConfigCache(this.postgres)

        // 2. Resolve outputs (topic + producer per logical name, env-controlled)
        const outputs = createTracesOutputsRegistry().build(this.producerRegistry, this.config)

        // 3. Traces ingestion consumer
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const usageBatch = new UsageRecordBatch(createUsageIngestionClient(this.config, 'apm_traces'), {
                unit: 'bytes',
                isTeamEnabled: usageReportTeamMatcher(this.config),
            })
            const consumer = createTracesIngestionConsumer(this.config, {
                teamManager,
                quotaLimiting,
                outputs,
                usageBatch,
                metricRulesCache,
                metricsEmitter,
                retentionRulesCache,
                tracingConfigCache,
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
