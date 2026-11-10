import { IntegrationType } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

export class IntegrationManagerService {
    private lazyLoader: LazyLoader<IntegrationType>

    constructor(
        private pubSub: PubSub,
        private postgres: PostgresRouter,
        private encryptedFields: EncryptedFields
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'integration_manager',
            loader: async (ids) => await this.fetchIntegrations(ids),
            loaderRetry: DEFAULT_LOADER_RETRY,
        })
        this.pubSub.on<{ integrationIds: IntegrationType['id'][] }>('reload-integrations', (message) => {
            logger.debug('⚡', '[PubSub] Reloading integrations!', { integrationIds: message.integrationIds })
            this.onIntegrationsReloaded(message.integrationIds)
        })
    }

    public async get(id: IntegrationType['id']): Promise<IntegrationType | null> {
        return (await this.lazyLoader.get(id.toString())) ?? null
    }

    public async getCheckingPrimaryOnMiss(id: IntegrationType['id']): Promise<IntegrationType | null> {
        const cached = await this.get(id)
        if (cached) {
            return cached
        }
        const fromPrimary = (await this.fetchIntegrations([id.toString()], PostgresUse.COMMON_WRITE))[id] ?? null
        if (fromPrimary) {
            this.lazyLoader.markForRefresh(id.toString())
        }
        return fromPrimary
    }

    public async getMany(ids: IntegrationType['id'][]): Promise<Record<IntegrationType['id'], IntegrationType | null>> {
        return await this.lazyLoader.getMany(ids.map((id) => id.toString()))
    }

    private onIntegrationsReloaded(integrationIds: IntegrationType['id'][]): void {
        this.lazyLoader.markForRefresh(integrationIds.map((id) => id.toString()))
    }

    private async fetchIntegrations(
        ids: string[],
        use: PostgresUse = PostgresUse.COMMON_READ
    ): Promise<Record<string, IntegrationType | undefined>> {
        logger.info('[IntegrationManager]', 'Fetching integrations', { ids })

        const response = await this.postgres.query<IntegrationType>(
            use,
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
