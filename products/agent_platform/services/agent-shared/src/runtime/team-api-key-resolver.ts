/**
 * Resolves the PostHog `phc_` project key for an agent's owning team. The
 * runner uses it as the bearer when calls go through PostHog's ai-gateway:
 * the gateway authenticates `phc_` against a hypercache mirror of Django's
 * team metadata and bills the team's prepaid wallet.
 *
 * The resolver hides the read off the hot path with a per-process cache.
 * Tokens rarely rotate, and a tiny staleness window (default 5 minutes) is
 * acceptable — a freshly-rotated key will start failing at the gateway
 * after the next cache miss anyway, so we accept a short window of
 * stale-bearer attempts in exchange for keeping the per-turn cost a hash
 * lookup.
 */

import type { Pool } from 'pg'

import { createLogger } from './logger'

export interface TeamApiKeyResolver {
    /** Returns the team's `phc_` project key, or throws if the team is missing. */
    resolve(teamId: number): Promise<string>
}

export interface PgTeamApiKeyResolverOpts {
    /** Cache TTL in ms. Default: 5 minutes. */
    ttlMs?: number
}

/**
 * Reads `posthog_team.api_token` from the main PostHog database. The token is
 * the team's public capture key (`phc_...`) — not secret-grade, but treated
 * as the team's bearer to PostHog services. The gateway resolves it to the
 * same `(team_id, allow_list, tier)` triple any SDK customer would.
 *
 * Pass the existing `pg.Pool` for the main PostHog DB; the resolver does not
 * own connection lifecycle.
 */
export class PgTeamApiKeyResolver implements TeamApiKeyResolver {
    private readonly log = createLogger('team-api-key-resolver')
    private readonly cache = new Map<number, { value: string; expires: number }>()
    private readonly ttlMs: number

    constructor(
        private readonly pool: Pool,
        opts: PgTeamApiKeyResolverOpts = {}
    ) {
        this.ttlMs = opts.ttlMs ?? 5 * 60_000
    }

    async resolve(teamId: number): Promise<string> {
        const cached = this.cache.get(teamId)
        if (cached && cached.expires > Date.now()) {
            return cached.value
        }
        const { rows } = await this.pool.query<{ api_token: string | null }>(
            'SELECT api_token FROM posthog_team WHERE id = $1',
            [teamId]
        )
        if (rows.length === 0) {
            throw new TeamApiKeyNotFoundError(`team_id=${teamId} not found`)
        }
        const value = rows[0].api_token
        if (!value) {
            throw new TeamApiKeyNotFoundError(`team_id=${teamId} has no api_token`)
        }
        this.cache.set(teamId, { value, expires: Date.now() + this.ttlMs })
        this.log.debug({ team_id: teamId }, 'team_api_key.cached')
        return value
    }

    /** Drops a single team's cache entry. Use after a known rotation. */
    invalidate(teamId: number): void {
        this.cache.delete(teamId)
    }

    /** Drops every cache entry. Tests + ops. */
    clear(): void {
        this.cache.clear()
    }
}

/** Thrown when a team has no api_token (deleted / never provisioned). */
export class TeamApiKeyNotFoundError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'TeamApiKeyNotFoundError'
    }
}
