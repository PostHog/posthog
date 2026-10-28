import { Counter } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

import { CohortMembershipRepository, StoredCohortMembership } from './cohort-membership-repository'

const cohortMembershipLookupsCounter = new Counter({
    name: 'cdp_cohort_membership_lookups_total',
    help: 'Point lookups against the behavioral cohorts cohort_membership table, by outcome.',
    labelNames: ['outcome'],
})

export class CohortMembershipLookupTimeoutError extends Error {
    constructor(timeoutMs: number) {
        super(`Cohort membership lookup timed out after ${timeoutMs}ms`)
        this.name = 'CohortMembershipLookupTimeoutError'
    }
    readonly isRetriable = true
}

// Bounds pool-acquire stalls and network black holes that a statement timeout cannot cover
export const DEFAULT_LOOKUP_TIMEOUT_MS = 1000

export class PostgresCohortMembershipRepository implements CohortMembershipRepository {
    constructor(
        private postgres: PostgresRouter,
        private lookupTimeoutMs: number = DEFAULT_LOOKUP_TIMEOUT_MS
    ) {}

    async getMemberCohortIds(teamId: number, personUuid: string): Promise<number[]> {
        const result = await this.withTimeout(
            this.postgres.query<{ cohort_id: string }>(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `SELECT cohort_id
                 FROM cohort_membership
                 WHERE team_id = $1
                   AND person_id = $2
                   AND in_cohort = true`,
                [teamId, personUuid],
                'fetchCohortMemberships'
            )
        )

        // BIGINT columns come back from pg as strings
        return result.rows.map((row) => Number(row.cohort_id))
    }

    async getCohortMembership(
        teamId: number,
        personUuid: string,
        cohortId: number,
        sinceVersion?: string
    ): Promise<StoredCohortMembership | null> {
        const result = await this.withTimeout(
            this.postgres.query<{ in_cohort: boolean; caught_up: boolean | null }>(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                // Compared in SQL because pg parses the '-infinity' sentinel to a non-date value.
                `SELECT in_cohort,
                        CASE WHEN $4::timestamp IS NULL OR version = '-infinity' THEN NULL
                             ELSE version >= $4::timestamp END AS caught_up
                 FROM cohort_membership
                 WHERE team_id = $1
                   AND cohort_id = $2
                   AND person_id = $3`,
                [teamId, cohortId, personUuid, sinceVersion ?? null],
                'fetchCohortMembership'
            )
        )
        const row = result.rows[0]
        return row ? { inCohort: row.in_cohort, caughtUp: row.caught_up } : null
    }

    private withTimeout<T>(queryPromise: Promise<T>): Promise<T> {
        return new Promise<T>((resolve, reject) => {
            // The timer and the query race. The query's handlers stay registered after the timer
            // wins and fire when it settles late, so this flag stops the loser from recording a
            // second outcome and double-counting the lookup in the metric.
            let settled = false
            const timer = setTimeout(() => {
                settled = true
                // Swallow the losing query's settlement so it can't become an unhandled rejection
                queryPromise.catch(() => undefined)
                cohortMembershipLookupsCounter.labels('timeout').inc()
                reject(new CohortMembershipLookupTimeoutError(this.lookupTimeoutMs))
            }, this.lookupTimeoutMs)

            queryPromise.then(
                (res) => {
                    if (settled) {
                        return
                    }
                    settled = true
                    clearTimeout(timer)
                    cohortMembershipLookupsCounter.labels('success').inc()
                    resolve(res)
                },
                (err) => {
                    if (settled) {
                        return
                    }
                    settled = true
                    clearTimeout(timer)
                    cohortMembershipLookupsCounter.labels('error').inc()
                    reject(err)
                }
            )
        })
    }
}
