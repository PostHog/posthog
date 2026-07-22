import { Counter, Histogram } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

// Mirrors the rust feature-flags provider (rust/feature-flags/src/cohorts/membership): 1s lookup
// timeout, short TTL cache. Unlike rust we throw on error instead of degrading to non-membership —
// an empty result would invert notInCohort, so the caller decides how to fail.
const LOOKUP_TIMEOUT_MS = 1000
const CACHE_TTL_MS = 60 * 1000
const CACHE_MAX_ENTRIES = 50_000

const cohortMembershipReadsCounter = new Counter({
    name: 'cdp_hogflow_cohort_membership_reads_total',
    help: 'Cohort membership lookups for hogflow conditions',
    labelNames: ['outcome'],
})

const cohortMembershipReadDuration = new Histogram({
    name: 'cdp_hogflow_cohort_membership_read_duration_ms',
    help: 'Duration of cohort membership lookups against the behavioral cohorts database',
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000],
})

const cohortMembershipCacheCounter = new Counter({
    name: 'cdp_hogflow_cohort_membership_cache',
    help: 'Cohort membership cache hits and misses',
    labelNames: ['result'],
})

type CacheEntry = {
    memberships: Map<number, boolean>
    expiresAt: number
}

export class CohortMembershipService {
    private cache = new Map<string, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    /**
     * Returns membership per requested cohort id from the realtime cohort_membership store.
     * A missing row means "not a member". Throws on query error or timeout — callers must
     * fail their cohort conditions closed rather than treat the person as a non-member,
     * since that would make notInCohort wrongly evaluate to true.
     */
    async fetchMemberships(teamId: number, personId: string, cohortIds: number[]): Promise<Map<number, boolean>> {
        if (cohortIds.length === 0) {
            return new Map()
        }

        const cacheKey = `${teamId}:${personId}`
        const now = Date.now()
        const cached = this.cache.get(cacheKey)
        const entry: CacheEntry =
            cached && cached.expiresAt > now ? cached : { memberships: new Map(), expiresAt: now + CACHE_TTL_MS }

        const missingIds = cohortIds.filter((id) => !entry.memberships.has(id))
        cohortMembershipCacheCounter.inc({ result: missingIds.length === 0 ? 'hit' : 'miss' })

        if (missingIds.length > 0) {
            const memberIds = await this.queryMemberships(teamId, personId, missingIds)
            for (const id of missingIds) {
                entry.memberships.set(id, memberIds.has(id))
            }
            this.cacheSet(cacheKey, entry)
        }

        return new Map(cohortIds.map((id) => [id, entry.memberships.get(id) === true]))
    }

    private async queryMemberships(teamId: number, personId: string, cohortIds: number[]): Promise<Set<number>> {
        const startTime = performance.now()
        try {
            const result = await this.withTimeout(
                this.postgres.query<{ cohort_id: number }>(
                    PostgresUse.BEHAVIORAL_COHORTS_RW,
                    `SELECT cohort_id FROM cohort_membership
                     WHERE team_id = $1 AND person_id = $2 AND cohort_id = ANY($3) AND in_cohort = true`,
                    [teamId, personId, cohortIds],
                    'fetchHogFlowCohortMemberships'
                )
            )
            cohortMembershipReadsCounter.inc({ outcome: 'success' })
            return new Set(result.rows.map((row) => Number(row.cohort_id)))
        } catch (error) {
            const isTimeout = error instanceof CohortMembershipTimeoutError
            cohortMembershipReadsCounter.inc({ outcome: isTimeout ? 'timeout' : 'error' })
            logger.error('Failed to fetch hogflow cohort memberships', {
                teamId,
                cohortIds,
                error,
            })
            throw error
        } finally {
            cohortMembershipReadDuration.observe(performance.now() - startTime)
        }
    }

    private async withTimeout<T>(promise: Promise<T>): Promise<T> {
        let timer: NodeJS.Timeout | undefined
        try {
            return await Promise.race([
                promise,
                new Promise<never>((_, reject) => {
                    timer = setTimeout(
                        () => reject(new CohortMembershipTimeoutError(`Cohort membership lookup timed out`)),
                        LOOKUP_TIMEOUT_MS
                    )
                }),
            ])
        } finally {
            clearTimeout(timer)
        }
    }

    private cacheSet(key: string, entry: CacheEntry): void {
        // Map preserves insertion order, so evicting the first key drops the oldest entry
        this.cache.delete(key)
        if (this.cache.size >= CACHE_MAX_ENTRIES) {
            const oldestKey = this.cache.keys().next().value
            if (oldestKey !== undefined) {
                this.cache.delete(oldestKey)
            }
        }
        this.cache.set(key, entry)
    }
}

export class CohortMembershipTimeoutError extends Error {}
