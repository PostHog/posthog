import {
    KafkaDownstreamProducerEnvConfig,
    getDefaultKafkaDownstreamProducerEnvConfig,
} from '@posthog/ingestion-common/outputs/producers'
import { initializePrometheusLabels } from '@posthog/node-common/api/router'
import { CommonConfig } from '@posthog/node-common/config'
import { KafkaBrokerConfig, RedisConnectionsConfig } from '@posthog/node-common/config/connections'
import { KafkaProducerRegistry } from '@posthog/node-common/outputs/kafka-producer-registry'
import {
    BaseServerConfig,
    CleanupResources,
    NodeServer,
    ServerLifecycle,
} from '@posthog/node-common/servers/base-server'
import { PostgresRouter, PostgresRouterConfig } from '@posthog/node-common/utils/db/postgres'
import { RedisConnectionConfig, createRedisPoolFromConfig } from '@posthog/node-common/utils/db/redis'
import { logger } from '@posthog/node-common/utils/logger'
import {
    SessionReplayOutputsConfig,
    type SessionReplayProducerName,
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
    getDefaultSessionReplayOutputsConfig,
} from '@posthog/replay-storage/config'
import {
    KafkaSessionreplayProducerEnvConfig,
    getDefaultKafkaSessionreplayProducerEnvConfig,
} from '@posthog/replay-storage/outputs/producer-config'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { SessionRecordingIngester } from '~/ingestion/pipelines/sessionreplay/consumer'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { createOutputsRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/registry'
import {
    IngestionSessionReplayServerConfig,
    buildSessionReplayRedisPools,
} from '~/ingestion/pipelines/sessionreplay/server-config'

import { getDefaultIngestionConsumerConfig } from '../ingestion/config'
import { RedisPool } from '../types'

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
