import { initializePrometheusLabels } from '~/common/api/router'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PostgresRouter, PostgresRouterConfig } from '~/common/utils/db/postgres'
import { RedisConnectionConfig, createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import {
    KafkaDownstreamProducerEnvConfig,
    getDefaultKafkaDownstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import {
    SessionReplayOutputsConfig,
    type SessionReplayProducerName,
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
    getDefaultSessionReplayOutputsConfig,
} from '~/ingestion/pipelines/sessionreplay/config'
import { SessionRecordingIngester, SessionRecordingIngesterConfig } from '~/ingestion/pipelines/sessionreplay/consumer'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { createOutputsRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/registry'
import { SessionConsoleLogStore } from '~/ingestion/pipelines/sessionreplay/sessions/session-console-log-store'
import {
    KafkaSessionreplayProducerEnvConfig,
    getDefaultKafkaSessionreplayProducerEnvConfig,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import { InternalLogsProducer, InternalLogsProducerConfig } from '~/logs/internal-logs-producer'

import { CdpConfig } from '../cdp/config'
import { parseInternalLogsSources } from '../cdp/services/monitoring/hog-function-monitoring.service'
import { CommonConfig } from '../common/config'
import { KafkaBrokerConfig, RedisConnectionsConfig, getDefaultIngestionConsumerConfig } from '../ingestion/config'
import { RedisPool } from '../types'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Complete config type for a session replay ingestion deployment.
 *
 * This is the union of:
 * - BaseServerConfig: HTTP server, profiling, pod termination lifecycle
 * - SessionRecordingIngesterConfig: recording consumer, S3, overflow
 * - KafkaBrokerConfig: Kafka connection and authentication
 * - RedisConnectionsConfig: Redis URLs, hosts, and pool sizing
 * - PostgresRouterConfig: database connection
 * - Internal logs producer: sends console logs to the logs product when `CDP_INTERNAL_LOGS_SOURCES` lists `session_replay`
 * - Remaining CommonConfig picks: server mode, observability
 *
 * This type is the source of truth for which env vars session replay ingestion deployments need.
 */
export type IngestionSessionReplayServerConfig = BaseServerConfig &
    SessionRecordingIngesterConfig &
    KafkaBrokerConfig &
    KafkaDownstreamProducerEnvConfig &
    KafkaSessionreplayProducerEnvConfig &
    SessionReplayOutputsConfig &
    RedisConnectionsConfig &
    PostgresRouterConfig &
    Pick<CdpConfig, 'CDP_INTERNAL_LOGS_SOURCES'> &
    InternalLogsProducerConfig &
    Pick<
        CommonConfig,
        'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'HEALTHCHECK_MAX_STALE_SECONDS' | 'KAFKA_HEALTHCHECK_SECONDS'
    >

/**
 * Builds the session-recording and restriction Redis pools a replay deployment needs.
 *
 * `sessionRecordingConnection` overrides where the session-recording pool points, for a lane that
 * runs against its own instance. The override belongs here rather than at the call site because
 * these pools connect eagerly (`autostart`), so a caller that built both and then discarded one
 * would leave a connected pool that nothing owns and nothing drains on shutdown.
 */
export function buildSessionReplayRedisPools(
    config: IngestionSessionReplayServerConfig,
    sessionRecordingConnection?: RedisConnectionConfig | null
): {
    redisPool: RedisPool
    restrictionRedisPool: RedisPool
} {
    const redisPool = createRedisPoolFromConfig({
        connection:
            sessionRecordingConnection ??
            (config.POSTHOG_SESSION_RECORDING_REDIS_HOST
                ? {
                      url: config.POSTHOG_SESSION_RECORDING_REDIS_HOST,
                      options: {
                          port: config.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379,
                          commandTimeout: config.SESSION_RECORDING_REDIS_TIMEOUT_MS,
                      },
                      name: 'session-recording-redis',
                  }
                : {
                      url: config.REDIS_URL,
                      options: { commandTimeout: config.SESSION_RECORDING_REDIS_TIMEOUT_MS },
                      name: 'session-recording-redis-fallback',
                  }),
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })

    const restrictionRedisPool = createRedisPoolFromConfig({
        connection: config.INGESTION_REDIS_HOST
            ? {
                  url: config.INGESTION_REDIS_HOST,
                  options: { port: config.INGESTION_REDIS_PORT },
                  name: 'ingestion-redis',
              }
            : config.POSTHOG_REDIS_HOST
              ? {
                    url: config.POSTHOG_REDIS_HOST,
                    options: { port: config.POSTHOG_REDIS_PORT, password: config.POSTHOG_REDIS_PASSWORD },
                    name: 'ingestion-redis',
                }
              : { url: config.REDIS_URL, name: 'ingestion-redis' },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })

    return { redisPool, restrictionRedisPool }
}

// Bounded so that shutdown still fits inside the pod's termination grace period.
const INTERNAL_LOGS_DRAIN_TIMEOUT_MS = 10_000

export class IngestionSessionReplayServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayServerConfig

    private postgres?: PostgresRouter
    private producerRegistry?: KafkaProducerRegistry<SessionReplayProducerName>
    private redisPool?: RedisPool
    private restrictionRedisPool?: RedisPool

    constructor(config: Partial<IngestionSessionReplayServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultIngestionConsumerConfig()),
            ...overrideConfigWithEnv(getDefaultSessionRecordingConfig()),
            ...overrideConfigWithEnv(getDefaultSessionRecordingApiConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaDownstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaSessionreplayProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultSessionReplayOutputsConfig()),
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
        initializePrometheusLabels(this.config.INGESTION_PIPELINE, this.config.INGESTION_LANE)

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const outputs = createOutputsRegistry().build(this.producerRegistry, this.config)
        logger.info('👍', 'Kafka ready')

        const pools = buildSessionReplayRedisPools(this.config)
        this.redisPool = pools.redisPool
        this.restrictionRedisPool = pools.restrictionRedisPool

        const internalLogsProducer = parseInternalLogsSources(this.config.CDP_INTERNAL_LOGS_SOURCES).has(
            'session_replay'
        )
            ? new InternalLogsProducer(this.config, new TeamManager(this.postgres))
            : undefined

        const ingester = new SessionRecordingIngester(
            this.config,
            this.postgres!,
            outputs,
            this.redisPool,
            this.restrictionRedisPool,
            {
                consoleLogStore: new SessionConsoleLogStore(outputs, {
                    messageLimit: this.config.SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT,
                    internalLogsProducer,
                }),
            }
        )
        await ingester.start()
        const service = ingester.service
        this.lifecycle.services.push({
            ...service,
            // Drains here rather than in additionalCleanup, which runs after Postgres and the HTTP agents close.
            onShutdown: async () => {
                try {
                    await service.onShutdown()
                } finally {
                    await internalLogsProducer?.drain(INTERNAL_LOGS_DRAIN_TIMEOUT_MS)
                }
            },
        })
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [this.redisPool, this.restrictionRedisPool].filter(Boolean) as RedisPool[],
            postgres: this.postgres,
            additionalCleanup: async () => {
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
