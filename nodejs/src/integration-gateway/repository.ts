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
     * Re-read a single row under the refresh lock, from the PRIMARY (not the replica): a stale
     * replica read would defeat the point of re-reading under the lock and could refresh with an
     * already-rotated refresh token, revoking the grant on strict-rotation providers. Returns null
     * if the row no longer exists.
     */
    async fetchOneForUpdate(id: number): Promise<IntegrationRow | null> {
        const response = await this.postgres.query<IntegrationRow>(
            PostgresUse.COMMON_WRITE,
            `SELECT id, team_id, kind, config, sensitive_config FROM posthog_integration WHERE id = $1`,
            [id],
            'integrationGatewayFetchOneForUpdate'
        )
        return response.rows[0] ?? null
    }

    /**
     * Persist a successful refresh and clear any prior refresh error, guarded by the encrypted
     * `refresh_token` we read under the lock (compare-and-swap). The Redis lock only excludes other
     * gateway heads; a Django reconnect can still write concurrently. Guarding on the exact stored
     * ciphertext means if anything changed the row since we read it (a reconnect rotating the token),
     * the update matches 0 rows and we discard rather than clobber the new credentials. Returns true
     * iff the row was updated.
     */
    async updateAfterRefresh(
        id: number,
        config: Record<string, any>,
        sensitiveConfig: Record<string, any>,
        expectedRefreshToken: string
    ): Promise<boolean> {
        const response = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_integration SET config = $1, sensitive_config = $2, errors = ''
             WHERE id = $3 AND sensitive_config->>'refresh_token' = $4`,
            [JSON.stringify(config), JSON.stringify(sensitiveConfig), id, expectedRefreshToken],
            'integrationGatewayUpdateAfterRefresh'
        )
        return (response.rowCount ?? 0) > 0
    }

    /**
     * Record a failed refresh: persist the updated backoff `config` and set the `TOKEN_REFRESH_FAILED`
     * sentinel (same one Django sets, surfaced as "reconnect this integration"). Compare-and-swap
     * guarded on the encrypted `refresh_token` read under the lock, so a concurrent reconnect — which
     * resets the backoff and clears errors — is never clobbered by our stale failure state. Returns
     * true iff the row was updated.
     */
    async recordRefreshFailure(
        id: number,
        config: Record<string, any>,
        expectedRefreshToken: string
    ): Promise<boolean> {
        const response = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_integration SET config = $1, errors = $2
             WHERE id = $3 AND sensitive_config->>'refresh_token' = $4`,
            [JSON.stringify(config), ERROR_TOKEN_REFRESH_FAILED, id, expectedRefreshToken],
            'integrationGatewayRecordRefreshFailure'
        )
        return (response.rowCount ?? 0) > 0
    }
}
