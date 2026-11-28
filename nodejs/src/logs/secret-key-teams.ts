import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import type { TeamManager } from '~/common/utils/team-manager'
import type { Team } from '~/types'

export const SECRET_KEY_PREFIX = 'phs_'
export const AUTH_TYPE_HEADER = 'auth-type'
export const AUTH_TYPE_SECRET_KEY = 'secret_key'
const SECRET_KEY_SCOPE = 'logs:write'

// capture-logs replaces a secret key with this digest, which has the form of `secure_value`.
const SECRET_KEY_DIGEST_PREFIX = 'sha256$'
const LOGGED_DIGEST_LENGTH = SECRET_KEY_DIGEST_PREFIX.length + 8
const SECRET_IN_TOKEN = /phs_|sha256\$/

export function isSecretKeyDigest(token: string): boolean {
    return token.startsWith(SECRET_KEY_DIGEST_PREFIX)
}

/** The part of a token that is safe to log, wherever a key or digest sits in it. A digest is as good as the key to a reader of the logs. */
export function loggableToken(token: string): string {
    const secret = SECRET_IN_TOKEN.exec(token)
    if (!secret) {
        return token
    }
    const markerEnd = secret.index + secret[0].length
    const digestEnd = secret.index + LOGGED_DIGEST_LENGTH
    const end = secret[0] === SECRET_KEY_DIGEST_PREFIX && token.length >= digestEnd ? digestEnd : markerEnd
    return token.slice(0, end).trimStart()
}

export function isUnhashedSecretKey(token: string): boolean {
    return token.trimStart().startsWith(SECRET_KEY_PREFIX)
}

type SecretKey = { teamId: number; canWriteLogs: boolean }

export class SecretKeyTeams {
    private readonly keys: LazyLoader<SecretKey>

    constructor(
        private readonly postgres: PostgresRouter,
        private readonly teamManager: Pick<TeamManager, 'getTeam'>
    ) {
        this.keys = new LazyLoader({
            name: 'SecretKeyTeams',
            refreshAgeMs: 2 * 60 * 1000,
            refreshJitterMs: 30 * 1000,
            loader: (hashes) => this.fetchKeys(hashes),
            loggableKey: loggableToken,
        })
    }

    public async getTeam(digest: string): Promise<Team | null> {
        const key = await this.keys.get(digest)
        return key?.canWriteLogs ? this.teamManager.getTeam(key.teamId) : null
    }

    /** True for a key without the logs:write scope too, so capture never turns it away once the scope is granted. */
    public async exists(digest: string): Promise<boolean> {
        return (await this.keys.get(digest)) !== null
    }

    private async fetchKeys(hashes: string[]): Promise<Record<string, SecretKey | null>> {
        const result = await this.postgres.query<{ secure_value: string; team_id: number; can_write_logs: boolean }>(
            PostgresUse.COMMON_READ,
            `SELECT secure_value, team_id, $2 = ANY(scopes) AS can_write_logs FROM posthog_projectsecretapikey WHERE secure_value = ANY($1)`,
            [hashes, SECRET_KEY_SCOPE],
            'fetch-secret-keys'
        )
        const keys: Record<string, SecretKey | null> = Object.fromEntries(hashes.map((hash) => [hash, null]))
        for (const row of result.rows) {
            keys[row.secure_value] = { teamId: row.team_id, canWriteLogs: row.can_write_logs }
        }
        return keys
    }
}

export async function isUnknownToken(
    token: string,
    secretKeyTeams: Pick<SecretKeyTeams, 'exists'> | undefined
): Promise<boolean> {
    if (isSecretKeyDigest(token)) {
        return secretKeyTeams ? !(await secretKeyTeams.exists(token)) : false
    }
    return !SECRET_IN_TOKEN.test(token)
}
