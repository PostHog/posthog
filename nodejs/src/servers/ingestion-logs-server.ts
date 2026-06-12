import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { HogFunctionManagerService } from '../cdp/services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../cdp/services/monitoring/hog-function-monitoring.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
import { CommonConfig } from '../common/config'
import { defaultConfig, overrideConfigWithEnv } from '../config/config'
import { createPosthogRedisConnectionConfig } from '../config/redis-pools'
import { DatabaseConnectionConfig, KafkaBrokerConfig, RedisConnectionsConfig } from '../ingestion/config'
import { KafkaProducerRegistry } from '../ingestion/outputs/kafka-producer-registry'
import {
    LogsIngestionConsumerConfig,
    LogsIngestionOutputsConfig,
    getDefaultLogsIngestionOutputsConfig,
} from '../logs-ingestion/config'
import { LogsIngestionConsumer } from '../logs-ingestion/logs-ingestion-consumer'
import { createProducerRegistry } from '../logs-ingestion/outputs/producer-registry'
import {
    KafkaWarpstreamIngestionProducerEnvConfig,
    KafkaWarpstreamLogsProducerEnvConfig,
    LogsProducerName,
    getDefaultKafkaWarpstreamIngestionProducerEnvConfig,
    getDefaultKafkaWarpstreamLogsProducerEnvConfig,
} from '../logs-ingestion/outputs/producers'
import { createLogsOutputsRegistry } from '../logs-ingestion/outputs/registry'
import { SamplingRulesCache } from '../logs-ingestion/sampling/sampling-rules-cache'
import { LogsTransformerService } from '../logs-ingestion/transformations/logs-transformer.service'
import { PluginServerService, RedisPool } from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { logger } from '../utils/logger'
import { PubSub } from '../utils/pubsub'
import { TeamManager } from '../utils/team-manager'
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
    Pick<
        CommonConfig,
        | 'LOG_LEVEL'
        | 'PLUGIN_SERVER_MODE'
        | 'CLOUD_DEPLOYMENT'
        | 'HEALTHCHECK_MAX_STALE_SECONDS'
        | 'ENCRYPTION_SALT_KEYS'
        | 'SITE_URL'
    >

export class IngestionLogsServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionLogsServerConfig

    private postgres?: PostgresRouter
    private posthogRedisPool?: RedisPool
    private producerRegistry?: KafkaProducerRegistry<LogsProducerName>
    private pubsub?: PubSub

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

        // 3. Hog log transformations (per-team execution is gated by
        // LOGS_TRANSFORMATIONS_ENABLED_TEAMS; the services themselves are cheap)
        this.pubsub = new PubSub(this.posthogRedisPool)
        await this.pubsub.start()
        const hogFunctionManager = new HogFunctionManagerService(
            this.postgres,
            this.pubsub,
            new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)
        )
        const hogFunctionMonitoring = new HogFunctionMonitoringService(outputs)
        const logsTransformer = new LogsTransformerService(hogFunctionManager, hogFunctionMonitoring, {
            siteUrl: this.config.SITE_URL,
            hogTimeoutMs: this.config.LOGS_TRANSFORMATIONS_HOG_TIMEOUT_MS,
            messageBudgetMs: this.config.LOGS_TRANSFORMATIONS_MESSAGE_BUDGET_MS,
            batchBudgetMs: this.config.LOGS_TRANSFORMATIONS_BATCH_BUDGET_MS,
            maxErrorLogsPerFunctionPerMessage: this.config.LOGS_TRANSFORMATIONS_MAX_ERROR_LOGS_PER_FUNCTION,
        })

        // 4. Logs ingestion consumer
        const serviceLoaders: (() => Promise<PluginServerService>)[] = []

        serviceLoaders.push(async () => {
            const consumer = new LogsIngestionConsumer(this.config, {
                teamManager,
                quotaLimiting,
                outputs,
                samplingRulesCache,
                logsTransformer,
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
            // PubSub holds a client from posthogRedisPool — it must stop in the services
            // phase, before the base server drains the pool, or stop() hangs.
            pubsub: this.pubsub,
            additionalCleanup: async () => {
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
