import { EncryptedFields } from '~/cdp/encryption-utils'
import { PubSub } from '~/utils/pubsub'

import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'

export type IntegrationType = {
    id: string
    team_id: number
    kind: string
    config: Record<string, any>
    sensitive_config: Record<string, any>
}

export class IntegrationManagerService {
    private lazyLoader: LazyLoader<IntegrationType>

    constructor(private pubSub: PubSub, private postgres: PostgresRouter, private encryptedFields: EncryptedFields) {
        this.lazyLoader = new LazyLoader({
            name: 'integration_manager',
            loader: async (ids) => await this.fetchIntegrations(ids),
        })
        this.pubSub.on<{ integrationIds: IntegrationType['id'][] }>('reload-integrations', (message) => {
            logger.debug('⚡', '[PubSub] Reloading integrations!', { integrationIds: message.integrationIds })
            this.onIntegrationsReloaded(message.integrationIds)
        })
    }

    public async get(id: IntegrationType['id']): Promise<IntegrationType | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    public async getMany(ids: IntegrationType['id'][]): Promise<Record<IntegrationType['id'], IntegrationType | null>> {
        return await this.lazyLoader.getMany(ids)
    }

    private onIntegrationsReloaded(integrationIds: IntegrationType['id'][]): void {
        this.lazyLoader.markForRefresh(integrationIds)
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
