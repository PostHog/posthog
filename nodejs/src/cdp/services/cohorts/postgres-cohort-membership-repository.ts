import { Counter } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

import { CohortMembershipRepository } from './cohort-membership-repository'

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
        const queryPromise = this.postgres.query<{ cohort_id: string }>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `SELECT cohort_id
             FROM cohort_membership
             WHERE team_id = $1
               AND person_id = $2
               AND in_cohort = true`,
            [teamId, personUuid],
            'fetchCohortMemberships'
        )

        const result = await new Promise<Awaited<typeof queryPromise>>((resolve, reject) => {
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

        // BIGINT columns come back from pg as strings
        return result.rows.map((row) => Number(row.cohort_id))
    }
}
