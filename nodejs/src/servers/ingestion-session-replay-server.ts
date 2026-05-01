import { CommonConfig } from '../common/config'
import { defaultConfig, overrideConfigWithEnv } from '../config/config'
import {
    KafkaIngestionProducerEnvConfig,
    KafkaWarpstreamProducerEnvConfig,
    getDefaultKafkaIngestionProducerEnvConfig,
    getDefaultKafkaWarpstreamProducerEnvConfig,
} from '../ingestion/common/config'
import { KafkaBrokerConfig, RedisConnectionsConfig } from '../ingestion/config'
import { KafkaProducerRegistry } from '../ingestion/outputs/kafka-producer-registry'
import {
    SessionReplayOutputsConfig,
    type SessionReplayProducerName,
    getDefaultSessionReplayOutputsConfig,
} from '../session-recording/config'
import { SessionRecordingIngester, SessionRecordingIngesterConfig } from '../session-recording/consumer'
import { createProducerRegistry } from '../session-recording/outputs/producer-registry'
import { createOutputsRegistry } from '../session-recording/outputs/registry'
import {
    KafkaDefaultProducerEnvConfig,
    getDefaultKafkaDefaultProducerEnvConfig,
} from '../session-replay/shared/outputs/producer-config'
import { RedisPool } from '../types'
import { PostgresRouter, PostgresRouterConfig } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { logger } from '../utils/logger'
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
 * - Remaining CommonConfig picks: server mode, observability
 *
 * This type is the source of truth for which env vars session replay ingestion deployments need.
 */
export type IngestionSessionReplayServerConfig = BaseServerConfig &
    SessionRecordingIngesterConfig &
    KafkaBrokerConfig &
    KafkaDefaultProducerEnvConfig &
    KafkaWarpstreamProducerEnvConfig &
    KafkaIngestionProducerEnvConfig &
    SessionReplayOutputsConfig &
    RedisConnectionsConfig &
    PostgresRouterConfig &
    Pick<
        CommonConfig,
        'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'HEALTHCHECK_MAX_STALE_SECONDS' | 'KAFKA_HEALTHCHECK_SECONDS'
    >

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
            ...overrideConfigWithEnv(getDefaultKafkaDefaultProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaWarpstreamProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaIngestionProducerEnvConfig()),
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
        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const outputs = createOutputsRegistry().build(this.producerRegistry, this.config)
        logger.info('👍', 'Kafka ready')

        // Session recording uses its own Redis instance with fallback to default
        this.redisPool = createRedisPoolFromConfig({
            connection: this.config.POSTHOG_SESSION_RECORDING_REDIS_HOST
                ? {
                      url: this.config.POSTHOG_SESSION_RECORDING_REDIS_HOST,
                      options: { port: this.config.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379 },
                      name: 'session-recording-redis',
                  }
                : { url: this.config.REDIS_URL, name: 'session-recording-redis-fallback' },
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })

        // Restriction manager needs to read from the same Redis as Django writes to
        this.restrictionRedisPool = createRedisPoolFromConfig({
            connection: this.config.INGESTION_REDIS_HOST
                ? {
                      url: this.config.INGESTION_REDIS_HOST,
                      options: { port: this.config.INGESTION_REDIS_PORT },
                      name: 'ingestion-redis',
                  }
                : this.config.POSTHOG_REDIS_HOST
                  ? {
                        url: this.config.POSTHOG_REDIS_HOST,
                        options: { port: this.config.POSTHOG_REDIS_PORT, password: this.config.POSTHOG_REDIS_PASSWORD },
                        name: 'ingestion-redis',
                    }
                  : { url: this.config.REDIS_URL, name: 'ingestion-redis' },
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })

        const ingester = new SessionRecordingIngester(
            this.config,
            this.postgres!,
            outputs,
            this.redisPool,
            this.restrictionRedisPool
        )
        await ingester.start()
        this.lifecycle.services.push(ingester.service)
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
