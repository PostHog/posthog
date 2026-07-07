import { SessionBatchMetrics } from '~/ingestion/pipelines/sessionreplay/sessions/metrics'
import { RetentionPeriod, isValidRetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { RedisPool, TeamId } from '~/types'

import { RetentionServiceMetrics } from './metrics'

/**
 * Outcome of resolving one session's retention. `resolved: false` is the expected, permanent
 * "can't determine retention" case (deleted/unknown team, invalid stored value) — the caller drops
 * that session. A transient failure (e.g. Redis unavailable) is thrown, not returned, so a retry
 * wrapper can re-run the lookup.
 */
export type RetentionResolution = { resolved: true; retentionPeriod: RetentionPeriod } | { resolved: false }

export class RetentionService {
    constructor(
        private redisPool: RedisPool,
        private teamService: TeamService,
        private keyPrefix = '@posthog/replay/'
    ) {}

    private generateRedisKey(teamId: TeamId, sessionId: string): string {
        // Retention is a per-team property, so the cache key must be scoped by team — a session id is
        // only unique within a team and can collide across teams.
        return `${this.keyPrefix}session-retention-${teamId}-${sessionId}`
    }

    /**
     * Resolves retention for a set of sessions (already deduped by `(teamId, sessionId)`). Cache hits
     * come from one Redis MGET; misses fall back to the team service (Postgres-backed) — one lookup
     * per distinct team — and are written back to Redis in a single pipeline. Returns a
     * {@link SessionMap} keyed by `(teamId, sessionId)`. Permanent failures map to `{ resolved: false }`;
     * a transient Redis or team service failure throws so the caller's retry wrapper can re-run the
     * whole lookup.
     */
    public async resolveSessionRetentions(sessions: SessionSet): Promise<SessionMap<RetentionResolution>> {
        const resolutions = new SessionMap<RetentionResolution>()
        if (sessions.size === 0) {
            return resolutions
        }

        const unique = [...sessions]

        const startTime = performance.now()
        const client = await this.redisPool.acquire()
        try {
            const redisKeys = unique.map(({ teamId, sessionId }) => this.generateRedisKey(teamId, sessionId))
            const cached = await client.mget(redisKeys)

            const missIndexes: number[] = []
            for (let i = 0; i < unique.length; i++) {
                const { teamId, sessionId } = unique[i]
                const value = cached[i]
                if (value === null) {
                    missIndexes.push(i)
                } else if (isValidRetentionPeriod(value)) {
                    resolutions.set(teamId, sessionId, { resolved: true, retentionPeriod: value })
                } else {
                    // A retention value the cache should never hold — crash rather than record with a
                    // wrong retention. Thrown without isRetriable so it propagates and takes the
                    // consumer down (same stance as an invalid value from the team service).
                    throw new Error(`Invalid cached retention value '${value}' for team ${teamId} session ${sessionId}`)
                }
            }

            if (missIndexes.length > 0) {
                // One team service lookup per distinct team, resolved concurrently, not per session.
                const teamRetentions = new Map<TeamId, RetentionPeriod | null>()
                await Promise.all(
                    [...new Set(missIndexes.map((i) => unique[i].teamId))].map(async (teamId) => {
                        teamRetentions.set(teamId, await this.teamService.getRetentionPeriodByTeamId(teamId))
                    })
                )

                const writeBack = client.pipeline()
                let hasWriteBack = false
                for (const i of missIndexes) {
                    const { teamId, sessionId } = unique[i]
                    const retentionPeriod = teamRetentions.get(teamId) ?? null
                    if (retentionPeriod === null) {
                        RetentionServiceMetrics.incrementLookupErrors()
                        resolutions.set(teamId, sessionId, { resolved: false })
                    } else {
                        resolutions.set(teamId, sessionId, { resolved: true, retentionPeriod })
                        // Cache for future batches, with a TTL of 24 hours.
                        writeBack.set(redisKeys[i], retentionPeriod, 'EX', 24 * 60 * 60)
                        hasWriteBack = true
                    }
                }
                if (hasWriteBack) {
                    await writeBack.exec()
                }
            }

            return resolutions
        } finally {
            await this.redisPool.release(client)
            SessionBatchMetrics.observeRetentionRedisLatency((performance.now() - startTime) / 1000)
        }
    }
}
