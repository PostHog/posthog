import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { EncryptedFields } from '~/common/utils/encryption-utils'
import { logger } from '~/common/utils/logger'
import { GatewayAuth } from '~/integration-gateway/auth'
import { CredentialCache } from '~/integration-gateway/cache'
import { IntegrationGatewayConfig, getDefaultIntegrationGatewayConfig, splitCsv } from '~/integration-gateway/config'
import { IntegrationService } from '~/integration-gateway/integration.service'
import { RefreshManager } from '~/integration-gateway/refresh/manager'
import { IntegrationRepository } from '~/integration-gateway/repository'
import { createGatewayRouter } from '~/integration-gateway/router'
import { HealthCheckResultOk, PluginsServerConfig, RedisPool } from '~/types'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Standalone deployment of the integration gateway: a hardened, isolated service that owns
 * third-party integration credential access (decrypt) and just-in-time OAuth token refresh, so
 * Fernet key material stops living in every consumer's environment. Callers authenticate with a
 * scoped JWT and read credentials through `POST /api/v1/credentials/fetch`.
 */
export type IntegrationGatewayServerConfig = PluginsServerConfig & IntegrationGatewayConfig

export class IntegrationGatewayServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IntegrationGatewayServerConfig

    private postgres?: PostgresRouter
    private redisPool?: RedisPool

    constructor(config: Partial<IntegrationGatewayServerConfig> = {}) {
        this.config = {
            ...defaultConfig,
            ...overrideConfigWithEnv(getDefaultIntegrationGatewayConfig()),
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

    private startServices(): Promise<void> {
        // Reuse the shared EncryptedFields helper (same key derivation as Django + CDP), with the
        // legacy PBKDF2 secret/salt keys enabled so pre-salt-keys rows stay readable.
        const encryptedFields = new EncryptedFields(
            this.config.ENCRYPTION_SALT_KEYS,
            [this.config.SECRET_KEY, this.config.SECRET_KEY_FALLBACKS].filter(Boolean).join(','),
            this.config.SALT_KEY
        )

        this.postgres = new PostgresRouter(this.config, 'integration-gateway')
        const repository = new IntegrationRepository(this.postgres)
        const cache = new CredentialCache(
            this.config.INTEGRATION_GATEWAY_CACHE_TTL_SECONDS,
            this.config.INTEGRATION_GATEWAY_CACHE_MAX_CAPACITY
        )

        // Token refresh is opt-in per kind; when disabled we never even connect to Redis and
        // Django's beat owns all refresh.
        const refreshKinds = splitCsv(this.config.INTEGRATION_GATEWAY_REFRESH_KINDS)
        let refreshManager: RefreshManager | null = null
        if (refreshKinds.length > 0) {
            this.redisPool = createRedisPoolFromConfig({
                connection: { url: this.config.REDIS_URL, name: 'integration-gateway-refresh' },
                poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
            })
            refreshManager = new RefreshManager(repository, encryptedFields, this.redisPool, this.config, refreshKinds)
            logger.info('🔑', '[integration-gateway] just-in-time token refresh enabled', { kinds: refreshKinds })
        }

        const service = new IntegrationService(repository, encryptedFields, cache, refreshManager)
        const auth = new GatewayAuth(
            `${this.config.INTEGRATION_GATEWAY_JWT_SECRET},${this.config.INTEGRATION_GATEWAY_JWT_SECRET_FALLBACKS}`
        )

        this.lifecycle.expressApp.use(
            '/',
            createGatewayRouter({
                service,
                auth,
                maxBatchSize: this.config.INTEGRATION_GATEWAY_MAX_BATCH_SIZE,
            })
        )

        this.lifecycle.services.push({
            id: 'integration-gateway',
            onShutdown: () => Promise.resolve(),
            healthcheck: () => new HealthCheckResultOk(),
        })

        return Promise.resolve()
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: this.redisPool ? [this.redisPool] : [],
            postgres: this.postgres,
        }
    }
}
