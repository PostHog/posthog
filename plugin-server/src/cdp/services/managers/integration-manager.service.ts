import { parseJSON } from '~/utils/json-parse'
import { PubSub } from '~/utils/pubsub'

import { Hub } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
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
    private started: boolean
    private pubSub: PubSub

    constructor(private hub: Hub) {
        this.started = false

        this.pubSub = new PubSub(this.hub, {
            'reload-integrations': (message) => {
                const { integrationIds } = parseJSON(message) as {
                    integrationIds: IntegrationType['id'][]
                }
                logger.debug('⚡', '[PubSub] Reloading integrations!', { integrationIds })
                this.onIntegrationsReloaded(integrationIds)
            },
        })
        this.lazyLoader = new LazyLoader({
            name: 'integration_manager',
            loader: async (ids) => await this.fetchIntegrations(ids),
        })
    }

    public async start(): Promise<void> {
        // TRICKY - when running with individual capabilities, this won't run twice but locally or as a complete service it will...
        if (this.started) {
            return
        }
        this.started = true
        await this.pubSub.start()
    }

    public async stop(): Promise<void> {
        await this.pubSub.stop()
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

        const response = await this.hub.postgres.query<IntegrationType>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, kind, config, sensitive_config FROM posthog_integration WHERE id = ANY($1)`,
            [ids],
            'fetchIntegrations'
        )

        const items = response.rows

        return items.reduce<Record<string, IntegrationType | undefined>>((acc, item) => {
            const sensitiveConfig = this.hub.encryptedFields.decryptObject(item.sensitive_config || {}, {
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
