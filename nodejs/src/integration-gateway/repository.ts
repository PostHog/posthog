import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

import { IntegrationRow } from './types'

/** Sole `errors` sentinel, matching Django's `ERROR_TOKEN_REFRESH_FAILED` (posthog/models/integration.py). */
export const ERROR_TOKEN_REFRESH_FAILED = 'TOKEN_REFRESH_FAILED'

/**
 * Data access for `posthog_integration`. `config`/`sensitive_config` are `jsonb` and decode
 * straight into objects; `id`/`team_id` are `int4` (Django `AutoField`) so decode as numbers —
 * matching `IntegrationManagerService`'s existing query (no `::bigint` cast, which would make
 * node-postgres return a string).
 */
export class IntegrationRepository {
    constructor(private postgres: PostgresRouter) {}

    async fetchByIds(ids: number[]): Promise<IntegrationRow[]> {
        if (ids.length === 0) {
            return []
        }
        const response = await this.postgres.query<IntegrationRow>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, kind, config, sensitive_config FROM posthog_integration WHERE id = ANY($1)`,
            [ids],
            'integrationGatewayFetchByIds'
        )
        return response.rows
    }

    /**
     * Re-read a single row under the refresh lock so we don't refresh a token a concurrent head (or
     * Django) already rotated. Returns null if the row no longer exists.
     */
    async fetchOne(id: number): Promise<IntegrationRow | null> {
        return (await this.fetchByIds([id]))[0] ?? null
    }

    /** Persist a successful refresh and clear any prior refresh error. Mirrors Django's write. */
    async updateAfterRefresh(
        id: number,
        config: Record<string, any>,
        sensitiveConfig: Record<string, any>
    ): Promise<void> {
        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_integration SET config = $1, sensitive_config = $2, errors = '' WHERE id = $3`,
            [JSON.stringify(config), JSON.stringify(sensitiveConfig), id],
            'integrationGatewayUpdateAfterRefresh'
        )
    }

    /** Record a failed refresh so the app surfaces "reconnect this integration" (same sentinel Django sets). */
    async markRefreshFailed(id: number): Promise<void> {
        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_integration SET errors = $1 WHERE id = $2`,
            [ERROR_TOKEN_REFRESH_FAILED, id],
            'integrationGatewayMarkRefreshFailed'
        )
    }
}
