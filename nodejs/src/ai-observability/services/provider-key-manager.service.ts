import { Team } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { LazyLoader } from '../../utils/lazy-loader'
import { logger } from '../../utils/logger'
import { PubSub } from '../../utils/pubsub'

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

    public async getProviderKey(id: ProviderKey['id']): Promise<ProviderKey | null> {
        return (await this.lazyLoader.get(id)) ?? null
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
