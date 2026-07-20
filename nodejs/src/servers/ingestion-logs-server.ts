import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { createPosthogRedisConnectionConfig } from '~/common/config/redis-pools'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
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
import { LogsTransformerService } from '~/logs/transformations/logs-transformer.service'

import type { CdpConfig } from '../cdp/config'
import { HogFunctionManagerService } from '../cdp/services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../cdp/services/monitoring/hog-function-monitoring.service'
import { HogWatcherService } from '../cdp/services/monitoring/hog-watcher.service'
import { EncryptedFields } from '../cdp/utils/encryption-utils'
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
    Pick<
        CommonConfig,
        | 'LOG_LEVEL'
        | 'PLUGIN_SERVER_MODE'
        | 'CLOUD_DEPLOYMENT'
        | 'HEALTHCHECK_MAX_STALE_SECONDS'
        | 'ENCRYPTION_SALT_KEYS'
        | 'SITE_URL'
    > &
    // HogWatcher for log transformations shares CDP's redis + tuning so function
    // health state is read and written where the API and CDP consumers expect it.
    Pick<
        CdpConfig,
        | 'CDP_REDIS_HOST'
        | 'CDP_REDIS_PORT'
        | 'CDP_REDIS_PASSWORD'
        | 'CDP_WATCHER_HOG_COST_TIMING_LOWER_MS'
        | 'CDP_WATCHER_HOG_COST_TIMING_UPPER_MS'
        | 'CDP_WATCHER_HOG_COST_TIMING'
        | 'CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS'
        | 'CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS'
        | 'CDP_WATCHER_ASYNC_COST_TIMING'
        | 'CDP_WATCHER_SEND_EVENTS'
        | 'CDP_WATCHER_BUCKET_SIZE'
        | 'CDP_WATCHER_REFILL_RATE'
        | 'CDP_WATCHER_TTL'
        | 'CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS'
        | 'CDP_WATCHER_THRESHOLD_DEGRADED'
        | 'CDP_WATCHER_STATE_LOCK_TTL'
        | 'CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS'
        | 'CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS'
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

        // HogWatcher on CDP's redis so function health state lands where the API reads it.
        // A sample rate of 0 (default) keeps it fully dormant — no Redis traffic.
        const cdpRedis = createRedisV2PoolFromConfig({
            connection: this.config.CDP_REDIS_HOST
                ? {
                      url: this.config.CDP_REDIS_HOST,
                      options: { port: this.config.CDP_REDIS_PORT, password: this.config.CDP_REDIS_PASSWORD },
                      name: 'logs-cdp-redis',
                  }
                : { url: this.config.REDIS_URL, name: 'logs-cdp-redis-fallback' },
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        const hogWatcher = new HogWatcherService(
            teamManager,
            {
                hogCostTimingLowerMs: this.config.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS,
                hogCostTimingUpperMs: this.config.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                hogCostTiming: this.config.CDP_WATCHER_HOG_COST_TIMING,
                asyncCostTimingLowerMs: this.config.CDP_WATCHER_ASYNC_COST_TIMING_LOWER_MS,
                asyncCostTimingUpperMs: this.config.CDP_WATCHER_ASYNC_COST_TIMING_UPPER_MS,
                asyncCostTiming: this.config.CDP_WATCHER_ASYNC_COST_TIMING,
                sendEvents: this.config.CDP_WATCHER_SEND_EVENTS,
                bucketSize: this.config.CDP_WATCHER_BUCKET_SIZE,
                refillRate: this.config.CDP_WATCHER_REFILL_RATE,
                ttl: this.config.CDP_WATCHER_TTL,
                automaticallyDisableFunctions: this.config.CDP_WATCHER_AUTOMATICALLY_DISABLE_FUNCTIONS,
                thresholdDegraded: this.config.CDP_WATCHER_THRESHOLD_DEGRADED,
                stateLockTtl: this.config.CDP_WATCHER_STATE_LOCK_TTL,
                observeResultsBufferTimeMs: this.config.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_TIME_MS,
                observeResultsBufferMaxResults: this.config.CDP_WATCHER_OBSERVE_RESULTS_BUFFER_MAX_RESULTS,
            },
            cdpRedis
        )

        const logsTransformer = new LogsTransformerService(
            hogFunctionManager,
            hogFunctionMonitoring,
            {
                siteUrl: this.config.SITE_URL,
                hogTimeoutMs: this.config.LOGS_TRANSFORMATIONS_HOG_TIMEOUT_MS,
                messageBudgetMs: this.config.LOGS_TRANSFORMATIONS_MESSAGE_BUDGET_MS,
                batchBudgetMs: this.config.LOGS_TRANSFORMATIONS_BATCH_BUDGET_MS,
                maxErrorLogsPerFunctionPerMessage: this.config.LOGS_TRANSFORMATIONS_MAX_ERROR_LOGS_PER_FUNCTION,
                hogWatcherSampleRate: this.config.LOGS_TRANSFORMATIONS_HOG_WATCHER_SAMPLE_RATE,
            },
            hogWatcher
        )

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
