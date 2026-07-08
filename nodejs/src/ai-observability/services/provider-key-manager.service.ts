import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

import { Team } from '../../types'

export type LLMProviderKeyState = 'unknown' | 'ok' | 'invalid' | 'error'

export interface ProviderKey {
    id: string
    team_id: Team['id']
    state: LLMProviderKeyState
}

export class ProviderKeyManagerService {
    private lazyLoader: LazyLoader<ProviderKey>

    constructor(
        private postgres: PostgresRouter,
        private pubSub: PubSub
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'provider_key_manager',
            loader: async (ids) => await this.fetchProviderKeys(ids),
            refreshAgeMs: 60_000,
            refreshNullAgeMs: 60_000,
            refreshJitterMs: 10_000,
        })

        this.pubSub.on<{ teamId: Team['id']; providerKeyIds: ProviderKey['id'][] }>(
            'reload-provider-keys',
            ({ teamId, providerKeyIds }) => {
                logger.debug('⚡', '[PubSub] Reloading provider keys!', { teamId, providerKeyIds })
                this.onProviderKeysReloaded(providerKeyIds)
            }
        )
    }

    public getProviderKey(id: ProviderKey['id']): Promise<ProviderKey | null> {
        return this.lazyLoader.get(id)
    }

    private onProviderKeysReloaded(providerKeyIds: ProviderKey['id'][]): void {
        this.lazyLoader.markForRefresh(providerKeyIds)
    }

    private async fetchProviderKeys(ids: string[]): Promise<Record<string, ProviderKey | undefined>> {
        logger.debug('[ProviderKeyManager]', 'Fetching provider keys', { ids })

        const response = await this.postgres.query<ProviderKey>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, state FROM llm_analytics_llmproviderkey WHERE id = ANY($1)`,
            [ids],
            'fetchProviderKeys'
        )

        return response.rows.reduce<Record<string, ProviderKey | undefined>>((acc, providerKey) => {
            acc[providerKey.id] = providerKey
            return acc
        }, {})
    }
}
