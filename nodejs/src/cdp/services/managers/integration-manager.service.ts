import { Counter } from 'prom-client'

import { IntegrationType } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

import { IntegrationGatewayService } from './integration-gateway.service'

const integrationGatewayRequestsCounter = new Counter({
    name: 'cdp_integration_gateway_requests_total',
    help: 'Integration credential fetches routed to the gateway, by outcome. "fallback" means the gateway was tried and we fell back to Postgres.',
    labelNames: ['result'],
})

export class IntegrationManagerService {
    private lazyLoader: LazyLoader<IntegrationType>

    constructor(
        private pubSub: PubSub,
        private postgres: PostgresRouter,
        private encryptedFields: EncryptedFields,
        // When set and enabled for the team, credentials are fetched from the Rust gateway instead of
        // decrypting in-process; any gateway error falls back to the Postgres path below.
        private gateway: IntegrationGatewayService | null = null
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'integration_manager',
            loader: async (ids) => await this.fetchIntegrations(ids),
        })
        this.pubSub.on<{ integrationIds: IntegrationType['id'][] }>('reload-integrations', (message) => {
            logger.debug('⚡', '[PubSub] Reloading integrations!', { integrationIds: message.integrationIds })
            this.onIntegrationsReloaded(message.integrationIds)
        })
    }

    public async get(id: IntegrationType['id'], teamId: number): Promise<IntegrationType | null> {
        return (await this.getMany([id], teamId))[id] ?? null
    }

    public async getMany(
        ids: IntegrationType['id'][],
        teamId: number
    ): Promise<Record<IntegrationType['id'], IntegrationType | null>> {
        if (this.gateway?.enabledForTeam(teamId)) {
            try {
                const result = await this.gateway.fetchMany(ids, teamId)
                integrationGatewayRequestsCounter.inc({ result: 'ok' })
                return result
            } catch (error) {
                // Fail open: a gateway blip must never break a hog function — fall back to Postgres.
                logger.warn('[IntegrationManager]', 'Gateway fetch failed, falling back to Postgres', {
                    teamId,
                    error: String(error),
                })
                integrationGatewayRequestsCounter.inc({ result: 'fallback' })
            }
        }
        return await this.getManyFromPostgres(ids)
    }

    private async getManyFromPostgres(
        ids: IntegrationType['id'][]
    ): Promise<Record<IntegrationType['id'], IntegrationType | null>> {
        return await this.lazyLoader.getMany(ids.map((id) => id.toString()))
    }

    private onIntegrationsReloaded(integrationIds: IntegrationType['id'][]): void {
        this.lazyLoader.markForRefresh(integrationIds.map((id) => id.toString()))
    }

    private async fetchIntegrations(ids: string[]): Promise<Record<string, IntegrationType | undefined>> {
        logger.info('[IntegrationManager]', 'Fetching integrations', { ids })

        const response = await this.postgres.query<IntegrationType>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, kind, config, sensitive_config FROM posthog_integration WHERE id = ANY($1)`,
            [ids],
            'fetchIntegrations'
        )

        const items = response.rows

        return items.reduce<Record<string, IntegrationType | undefined>>((acc, item) => {
            const sensitiveConfig = this.encryptedFields.decryptObject(item.sensitive_config || {}, {
                ignoreDecryptionErrors: true,
            })

            acc[item.id] = {
                ...item,
                sensitive_config: sensitiveConfig,
            }

            return acc
        }, {})
    }
}
