import { parseInternalLogsSources } from '@posthog/hog-engine/cdp/services/monitoring/hog-function-monitoring.service'
import { getDefaultKafkaDownstreamProducerEnvConfig } from '@posthog/ingestion-common/outputs/producers'
import { initializePrometheusLabels } from '@posthog/node-common/api/router'
import { InternalLogsProducer } from '@posthog/node-common/logs/internal-logs-producer'
import { KafkaProducerRegistry } from '@posthog/node-common/outputs/kafka-producer-registry'
import { CleanupResources, NodeServer, ServerLifecycle } from '@posthog/node-common/servers/base-server'
import { PostgresRouter } from '@posthog/node-common/utils/db/postgres'
import { logger } from '@posthog/node-common/utils/logger'
import { TeamManager } from '@posthog/node-common/utils/team-manager'
import {
    type SessionReplayProducerName,
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
    getDefaultSessionReplayOutputsConfig,
} from '@posthog/replay-storage/config'
import { getDefaultKafkaSessionreplayProducerEnvConfig } from '@posthog/replay-storage/outputs/producer-config'

import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { SessionRecordingIngester } from '~/ingestion/pipelines/sessionreplay/consumer'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { createOutputsRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/registry'
import {
    IngestionSessionReplayServerConfig,
    buildSessionReplayRedisPools,
} from '~/ingestion/pipelines/sessionreplay/server-config'
import { SessionConsoleLogStore } from '~/ingestion/pipelines/sessionreplay/sessions/session-console-log-store'

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
 * - Internal logs producer: sends console logs to the logs product when `CDP_INTERNAL_LOGS_SOURCES` lists `session_replay`
 * - Remaining CommonConfig picks: server mode, observability
 *
 * This type is the source of truth for which env vars session replay ingestion deployments need.
 */
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
