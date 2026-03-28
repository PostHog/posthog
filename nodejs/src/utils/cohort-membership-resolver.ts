import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

const toKey = (teamId: number, personId: string): string => `${teamId}:${personId}`

const fromKey = (key: string): { teamId: number; personId: string } => {
    const sepIdx = key.indexOf(':')
    return {
        teamId: parseInt(key.substring(0, sepIdx)),
        personId: key.substring(sepIdx + 1),
    }
}

/**
 * Resolves cohort memberships for (team, person) keys using LazyLoader.
 */
export class CohortMembershipResolver {
    private loader: LazyLoader<number[]>

    constructor(postgres: PostgresRouter) {
        this.loader = new LazyLoader({
            name: 'cohort_membership_resolver',
            refreshAgeMs: 60 * 1000,
            refreshJitterMs: 5 * 1000,
            loader: async (keys: string[]): Promise<Record<string, number[] | null | undefined>> => {
                const parsed = keys.map(fromKey)

                const teamIds = parsed.map((p) => p.teamId)
                const personIds = parsed.map((p) => p.personId)

                const result = await postgres.query(
                    PostgresUse.BEHAVIORAL_COHORTS_RW,
                    `SELECT cm.team_id, cm.person_id, cm.cohort_id, cm.in_cohort
                     FROM cohort_membership cm
                     INNER JOIN UNNEST($1::int[], $2::uuid[]) AS params(team_id, person_id)
                       ON cm.team_id = params.team_id AND cm.person_id = params.person_id
                     WHERE cm.in_cohort = TRUE`,
                    [teamIds, personIds],
                    'fetchBulkCohortMemberships'
                )

                // Initialize all keys with empty arrays
                const resultRecord: Record<string, number[]> = {}
                for (const key of keys) {
                    resultRecord[key] = []
                }
                // Populate with actual memberships
                for (const row of result.rows) {
                    const key = toKey(Number(row.team_id), row.person_id)
                    if (resultRecord[key]) {
                        resultRecord[key].push(Number(row.cohort_id))
                    }
                }

                return resultRecord
            },
        })
    }

    /**
     * Returns a list of cohort IDs the person belongs to.
     * Concurrent calls are batched by the LazyLoader.
     */
    async getPersonCohortIds(teamId: number, personId: string): Promise<number[]> {
        if (!personId) {
            return []
        }
        return (await this.loader.get(toKey(teamId, personId))) ?? []
    }
}
