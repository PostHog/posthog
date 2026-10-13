import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

export type ProjectTeam = { id: number; api_token: string }

/** The longest value `posthog_team.api_token` can hold. A longer token cannot match a project. */
export const MAX_PROJECT_TOKEN_LENGTH = 200

/** Resolves a project token to its team by exact match on `api_token` and nothing else.
 *
 * The shared TeamManager is not used here. It caches every looked-up key for minutes, and on a
 * public endpoint the key is whatever the caller sends. A short refresh makes a reset token stop
 * working within seconds, close to Django, which invalidates its cache on reset.
 */
export class ProjectTokenLookup {
    private loader: LazyLoader<ProjectTeam>

    constructor(postgres: PostgresRouter) {
        this.loader = new LazyLoader({
            name: 'PushProjectTokens',
            refreshAgeMs: 5_000,
            refreshJitterMs: 1_000,
            // Matches the service's own negative cache, which answers repeats before this is asked.
            refreshNullAgeMs: 60_000,
            maxSize: 50_000,
            loader: async (tokens: string[]) => {
                const { rows } = await postgres.query<ProjectTeam>(
                    PostgresUse.COMMON_READ,
                    'SELECT id, api_token FROM posthog_team WHERE api_token = ANY($1)',
                    [tokens],
                    'fetchPushProjectTokens'
                )
                const result: Record<string, ProjectTeam | null> = {}
                for (const token of tokens) {
                    result[token] = null
                }
                for (const row of rows) {
                    result[row.api_token] = { id: Number(row.id), api_token: row.api_token }
                }
                return result
            },
        })
    }

    public async getTeamByToken(token: string): Promise<ProjectTeam | null> {
        if (token.length > MAX_PROJECT_TOKEN_LENGTH) {
            return null
        }
        return await this.loader.get(token)
    }
}
