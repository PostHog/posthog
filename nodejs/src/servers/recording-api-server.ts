import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PostgresRouter, PostgresRouterConfig } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import {
    getDefaultSessionRecordingApiConfig,
    getDefaultSessionRecordingConfig,
} from '~/ingestion/pipelines/sessionreplay/config'
import {
    KafkaSessionreplayProducerEnvConfig,
    getDefaultKafkaSessionreplayProducerEnvConfig,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import { createProducerRegistry } from '~/session-replay/recording-api/outputs/producer-registry'
import { createOutputsRegistry } from '~/session-replay/recording-api/outputs/registry'
import { RecordingApi } from '~/session-replay/recording-api/recording-api'
import {
    RecordingApiConfig,
    RecordingApiOutputsConfig,
    type RecordingApiProducerName,
    getDefaultRecordingApiOutputsConfig,
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

        const api = new RecordingApi(this.config, this.postgres!, outputs)
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
