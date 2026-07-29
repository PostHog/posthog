import { defaultConfig, overrideConfigWithEnv } from '~/common/config/config'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { EncryptedFields } from '~/common/utils/encryption-utils'
import { logger } from '~/common/utils/logger'
import { CredentialCache } from '~/integration-gateway/cache'
import {
    IntegrationGatewayConfig,
    getDefaultIntegrationGatewayConfig,
    parseRefreshTeams,
    splitCsv,
} from '~/integration-gateway/config'
import { IntegrationService } from '~/integration-gateway/integration.service'
import { RefreshManager } from '~/integration-gateway/refresh/manager'
import { IntegrationRepository } from '~/integration-gateway/repository'
import { createGatewayRouter } from '~/integration-gateway/router'
import { HealthCheckResultOk, PluginsServerConfig, RedisPool } from '~/types'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'

/**
 * Standalone deployment of the integration gateway: a hardened, isolated service that owns
 * third-party integration credential access (decrypt) and just-in-time OAuth token refresh, so
 * Fernet key material stops living in every consumer's environment. Callers read credentials
 * through `POST /api/v1/credentials/fetch`; access is bounded at the network layer by a Cilium
 * NetworkPolicy (no application-level auth secret), and the request carries the team and caller.
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
        // The gateway intentionally holds ONLY the current ENCRYPTION_SALT_KEYS — not the legacy
        // PBKDF2 SECRET_KEY/SALT_KEY material — to keep its crown-jewel key footprint minimal.
        // TODO: before enabling the gateway for a team in prod, confirm no posthog_integration rows
        // are still legacy-encrypted — `audit_encrypted_field_keys --field
        // posthog.Integration.sensitive_config` must report legacy=0 (re-encrypt any stragglers
        // first). Legacy-encrypted rows will NOT decrypt here.
        const encryptedFields = new EncryptedFields(this.config.ENCRYPTION_SALT_KEYS)

        this.postgres = new PostgresRouter(this.config, 'integration-gateway')
        const repository = new IntegrationRepository(this.postgres)
        const cache = new CredentialCache(
            this.config.INTEGRATION_GATEWAY_CACHE_TTL_SECONDS,
            this.config.INTEGRATION_GATEWAY_CACHE_MAX_CAPACITY
        )

        // Token refresh is opt-in per (kind, team): a kind must be in REFRESH_KINDS (capability) and
        // the row's team in REFRESH_TEAMS (rollout). If either is empty no row is ever owned, so we
        // never even connect to Redis and Django's beat owns all refresh.
        const refreshKinds = splitCsv(this.config.INTEGRATION_GATEWAY_REFRESH_KINDS)
        const refreshTeams = parseRefreshTeams(this.config.INTEGRATION_GATEWAY_REFRESH_TEAMS)
        const refreshTeamsEmpty = refreshTeams !== '*' && refreshTeams.size === 0
        let refreshManager: RefreshManager | null = null
        if (refreshKinds.length > 0 && !refreshTeamsEmpty) {
            this.redisPool = createRedisPoolFromConfig({
                connection: { url: this.config.REDIS_URL, name: 'integration-gateway-refresh' },
                poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
                poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
            })
            refreshManager = new RefreshManager(
                repository,
                encryptedFields,
                this.redisPool,
                this.config,
                refreshKinds,
                refreshTeams
            )
            logger.info('🔑', '[integration-gateway] just-in-time token refresh enabled', {
                kinds: refreshKinds,
                teams: refreshTeams === '*' ? '*' : [...refreshTeams],
            })
        }

        const service = new IntegrationService(repository, encryptedFields, cache, refreshManager)

        this.lifecycle.expressApp.use(
            '/',
            createGatewayRouter({
                service,
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
