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
import {
    assertRecordingApiRoleAuthConfigured,
    internalApiAuthExcludedPathPrefixes,
} from '~/session-replay/recording-api/auth'
import { createProducerRegistry } from '~/session-replay/recording-api/outputs/producer-registry'
import { createOutputsRegistry } from '~/session-replay/recording-api/outputs/registry'
import { RecordingApi } from '~/session-replay/recording-api/recording-api'
import {
    RecordingApiConfig,
    RecordingApiOutputsConfig,
    type RecordingApiProducerName,
    RecordingApiRole,
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
    private readonly role: RecordingApiRole

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
        this.role = parseRecordingApiRole(this.config.RECORDING_API_ROLE)
        // recording-api verifies a team-scoped JWT per route, so exempt its routes from the
        // shared-secret middleware (callers send a Bearer token, not X-Internal-Api-Secret).
        this.lifecycle = new ServerLifecycle(this.config, {
            internalApiAuthExcludedPathPrefixes: internalApiAuthExcludedPathPrefixes(this.role),
            readOnlyPathPrefixes: ['/replay-blocks/'],
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
        assertRecordingApiRoleAuthConfigured({
            role: this.role,
            isProd: isProdEnv(),
            blocksJwtSecret: this.config.RECORDING_API_BLOCKS_JWT_SECRET,
            jwtSecret: this.config.RECORDING_API_JWT_SECRET,
        })

        // A public process serves only browser block reads, so it never connects to Postgres or Kafka.
        let outputs: ReturnType<ReturnType<typeof createOutputsRegistry>['build']> | undefined
        if (this.role !== 'public') {
            this.postgres = new PostgresRouter(this.config, this.config.PLUGIN_SERVER_MODE ?? undefined)
            logger.info('👍', 'Postgres Router ready')

            logger.info('🤔', 'Connecting to Kafka...')
            this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
            outputs = createOutputsRegistry().build(this.producerRegistry, this.config)
            logger.info('👍', 'Kafka ready')
        }

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
