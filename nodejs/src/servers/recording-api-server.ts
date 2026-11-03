import { hasJwtKeys } from '~/cdp/utils/jwt-utils'
import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PostgresRouter, PostgresRouterConfig } from '~/common/utils/db/postgres'
import { isProdEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import {
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
} from '~/ingestion/pipelines/sessionreplay/config'
import {
    KafkaSessionreplayProducerEnvConfig,
    getDefaultKafkaSessionreplayProducerEnvConfig,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import { assertRecordingApiAuthConfigured } from '~/session-replay/recording-api/auth'
import { createProducerRegistry } from '~/session-replay/recording-api/outputs/producer-registry'
import { createOutputsRegistry } from '~/session-replay/recording-api/outputs/registry'
import { RecordingApi } from '~/session-replay/recording-api/recording-api'
import {
    RecordingApiConfig,
    RecordingApiOutputsConfig,
    type RecordingApiProducerName,
    getDefaultRecordingApiAuthConfig,
    getDefaultRecordingApiBlocksConfig,
    getDefaultRecordingApiOutputsConfig,
    parseRecordingApiRole,
} from '~/session-replay/recording-api/types'

import { CommonConfig } from '../common/config'
import { KafkaBrokerConfig } from '../ingestion/config'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

export type RecordingApiServerConfig = BaseServerConfig &
    RecordingApiConfig &
    KafkaBrokerConfig &
    KafkaSessionreplayProducerEnvConfig &
    RecordingApiOutputsConfig &
    PostgresRouterConfig &
    Pick<
        CommonConfig,
        'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'HEALTHCHECK_MAX_STALE_SECONDS' | 'KAFKA_HEALTHCHECK_SECONDS'
    >

export class RecordingApiServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: RecordingApiServerConfig

    private postgres?: PostgresRouter
    private producerRegistry?: KafkaProducerRegistry<RecordingApiProducerName>

    constructor(config: Partial<RecordingApiServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultSessionRecordingConfig()),
            ...overrideConfigWithEnv(getDefaultSessionRecordingApiConfig()),
            ...overrideConfigWithEnv(getDefaultKafkaSessionreplayProducerEnvConfig()),
            ...overrideConfigWithEnv(getDefaultRecordingApiOutputsConfig()),
            ...overrideConfigWithEnv(getDefaultRecordingApiAuthConfig()),
            ...overrideConfigWithEnv(getDefaultRecordingApiBlocksConfig()),
            ...config,
        }
        // recording-api verifies a team-scoped JWT per route, so exempt its routes from the
        // shared-secret middleware (callers send a Bearer token, not X-Internal-Api-Secret).
        // The browser block route checks its own browser token, so a process serving it exempts it too.
        const servesPublicRoutes = parseRecordingApiRole(this.config.RECORDING_API_ROLE) !== 'internal'
        this.lifecycle = new ServerLifecycle(this.config, {
            internalApiAuthExcludedPathPrefixes: ['/api/projects/', ...(servesPublicRoutes ? ['/replay-blocks/'] : [])],
        })
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
        const role = parseRecordingApiRole(this.config.RECORDING_API_ROLE)
        // The browser route accepts only browser tokens, so no other secret can stand in for the blocks secret.
        if (role !== 'internal' && isProdEnv() && !hasJwtKeys(this.config.RECORDING_API_BLOCKS_JWT_SECRET || '')) {
            throw new Error('recording-api serving browser blocks needs RECORDING_API_BLOCKS_JWT_SECRET in production')
        }
        // A public process holds no service secret at all, so it has no internal auth to check.
        if (role !== 'public') {
            assertRecordingApiAuthConfigured({
                isProd: isProdEnv(),
                jwtSecret: this.config.RECORDING_API_JWT_SECRET,
                allowLegacySecret: this.config.RECORDING_API_ALLOW_LEGACY_SECRET,
                legacySecret: this.config.INTERNAL_API_SECRET,
            })
        }

        // A public process serves only browser block reads, so it never connects to Postgres or Kafka.
        if (role === 'public') {
            const api = new RecordingApi(this.config)
            this.lifecycle.expressApp.use('/', api.router())
            await api.start()
            this.lifecycle.services.push(api.service)
            return
        }

        this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
        logger.info('👍', 'Postgres Router ready')

        logger.info('🤔', 'Connecting to Kafka...')
        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const outputs = createOutputsRegistry().build(this.producerRegistry, this.config)
        logger.info('👍', 'Kafka ready')

        const api = new RecordingApi(this.config, this.postgres, outputs)
        this.lifecycle.expressApp.use('/', api.router())
        await api.start()
        this.lifecycle.services.push(api.service)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
            postgres: this.postgres,
            additionalCleanup: async () => {
                await this.producerRegistry?.disconnectAll()
            },
        }
    }
}
