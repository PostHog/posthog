import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import type { TeamManager } from '~/common/utils/team-manager'
import type { Team } from '~/types'

export const SECRET_KEY_PREFIX = 'phs_'
export const AUTH_TYPE_HEADER = 'auth-type'
export const AUTH_TYPE_SECRET_KEY = 'secret_key'
export const SECRET_KEY_SCOPE = 'logs:write'

// capture-logs replaces a secret key with this digest, which has the form of `secure_value`.
export const SECRET_KEY_DIGEST_PREFIX = 'sha256$'

export function isSecretKeyDigest(token: string): boolean {
    return token.startsWith(SECRET_KEY_DIGEST_PREFIX)
}

/** A key that no capture service hashed. It is never looked up, logged or recorded. */
export function isSecretKey(token: string): boolean {
    return token.trimStart().startsWith(SECRET_KEY_PREFIX)
}

/** Resolves the digest of a project secret API key to its team. */
export class SecretKeyTeams {
    private readonly teamIds: LazyLoader<number>

    constructor(
        private readonly postgres: PostgresRouter,
        private readonly teamManager: Pick<TeamManager, 'getTeam'>
    ) {
        this.teamIds = new LazyLoader({
            name: 'SecretKeyTeams',
            refreshAgeMs: 2 * 60 * 1000,
            refreshJitterMs: 30 * 1000,
            loader: (hashes) => this.fetchTeamIds(hashes),
        })
    }

    public async getTeam(digest: string): Promise<Team | null> {
        const teamId = await this.teamIds.get(digest)
        return teamId === null ? null : this.teamManager.getTeam(teamId)
    }

    private async fetchTeamIds(hashes: string[]): Promise<Record<string, number | null>> {
        const result = await this.postgres.query<{ secure_value: string; team_id: number }>(
            PostgresUse.COMMON_READ,
            `SELECT secure_value, team_id FROM posthog_projectsecretapikey WHERE secure_value = ANY($1) AND $2 = ANY(scopes)`,
            [hashes, SECRET_KEY_SCOPE],
            'fetch-secret-key-teams'
        )
        const teamIds: Record<string, number | null> = Object.fromEntries(hashes.map((hash) => [hash, null]))
        for (const row of result.rows) {
            teamIds[row.secure_value] = row.team_id
        }
        return teamIds
    }
}
