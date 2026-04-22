import { CommonConfig } from '../common/config'
import { defaultConfig } from '../config/config'
import { RecordingApi } from '../session-replay/recording-api/recording-api'
import { RecordingApiConfig } from '../session-replay/recording-api/types'
import { PostgresRouter, PostgresRouterConfig } from '../utils/db/postgres'
import { logger } from '../utils/logger'
import { BaseServerConfig, CleanupResources, NodeServer, ServerLifecycle } from './base-server'

export type RecordingApiServerConfig = BaseServerConfig &
    RecordingApiConfig &
    PostgresRouterConfig &
    Pick<
        CommonConfig,
        'LOG_LEVEL' | 'PLUGIN_SERVER_MODE' | 'HEALTHCHECK_MAX_STALE_SECONDS' | 'KAFKA_HEALTHCHECK_SECONDS'
    >

export class RecordingApiServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: RecordingApiServerConfig

    private postgres?: PostgresRouter

    constructor(config: Partial<RecordingApiServerConfig> = {}) {
        this.config = { ...defaultConfig, ...config }
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

        const api = new RecordingApi(this.config, this.postgres!)
        this.lifecycle.expressApp.use('/', api.router())
        await api.start()
        this.lifecycle.services.push(api.service)
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
            postgres: this.postgres,
        }
    }
}
