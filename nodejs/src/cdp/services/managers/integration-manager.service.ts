import { Counter } from 'prom-client'

import { IntegrationType } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

import { IntegrationGatewayService } from './integration-gateway.service'

const gatewayRequestsCounter = new Counter({
    name: 'cdp_integration_gateway_requests_total',
    help: 'Integration reads attempted via the gateway, by outcome. result: ok | fallback.',
    labelNames: ['result'],
})

export class IntegrationManagerService {
    private lazyLoader: LazyLoader<IntegrationType>

    constructor(
        private pubSub: PubSub,
        private postgres: PostgresRouter,
        private encryptedFields: EncryptedFields,
        private gateway: IntegrationGatewayService | null = null
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'integration_manager',
            loader: (ids) => this.fetchIntegrations(ids),
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
        // Route through the gateway when it's rolled out to this team; fail open to Postgres so a
        // gateway outage never blocks credential reads.
        if (this.gateway?.enabledForTeam(teamId)) {
            try {
                const result = await this.gateway.fetchMany(ids, teamId)
                gatewayRequestsCounter.inc({ result: 'ok' })
                return result
            } catch (error) {
                logger.warn('[IntegrationManager]', 'Gateway fetch failed, falling back to Postgres', {
                    error: String(error),
                })
                gatewayRequestsCounter.inc({ result: 'fallback' })
            }
        }
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
