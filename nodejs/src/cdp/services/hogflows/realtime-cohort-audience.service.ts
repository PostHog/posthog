import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

/** Members read per page. Matches the default page size of the Django audience query. */
export const REALTIME_COHORT_AUDIENCE_PAGE_SIZE = 5000

const MEMBER_PAGE_TIMEOUT_MS = 30_000
// Covers the connection checkout and BEGIN too, which the statement timeout can't bound.
export const MEMBER_PAGE_DEADLINE_MS = 60_000

export type RealtimeCohortAudiencePage = {
    ids: string[]
    cursor: string | null
    has_more: boolean
}

/**
 * Pages the members of a realtime cohort straight from the realtime pipeline's Postgres table.
 *
 * Postgres is the source of truth for realtime membership, so there is no copy to lag behind it.
 * The workflow worker loads each person when it runs, so the page only carries person ids. Django
 * decides which audiences take this path, and passes the cohort with the batch run.
 */
export class RealtimeCohortAudienceService {
    constructor(private postgres: PostgresRouter) {}

    async getMemberPage(
        cohortTeamId: number,
        cohortId: number,
        cursor: string | null,
        pageSize: number = REALTIME_COHORT_AUDIENCE_PAGE_SIZE
    ): Promise<RealtimeCohortAudiencePage> {
        const afterCursor = cursor === null ? '' : 'AND person_id > $4::uuid'
        const values: unknown[] = [cohortTeamId, cohortId, pageSize]
        if (cursor !== null) {
            values.push(cursor)
        }
        // The resolver heartbeats its job while it waits, so a stalled read would hold the job without
        // ever failing. The timeouts turn a stall into an error, which the resolver retries.
        const read = this.postgres.transaction(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            'getRealtimeCohortMemberPage',
            async (tx) => {
                await this.postgres.query(
                    tx,
                    `SET LOCAL statement_timeout = ${MEMBER_PAGE_TIMEOUT_MS}`,
                    undefined,
                    'setRealtimeCohortMemberPageTimeout'
                )
                return await this.postgres.query<{ person_id: string }>(
                    tx,
                    `
                        SELECT person_id
                        FROM cohort_membership
                        WHERE team_id = $1 AND cohort_id = $2 AND in_cohort ${afterCursor}
                        ORDER BY person_id
                        LIMIT $3
                    `,
                    values,
                    'getRealtimeCohortMemberPage'
                )
            }
        )
        let deadline: NodeJS.Timeout | undefined
        const result = await Promise.race([
            read,
            new Promise<never>((_, reject) => {
                deadline = setTimeout(
                    () =>
                        reject(new Error(`Realtime cohort member page took longer than ${MEMBER_PAGE_DEADLINE_MS}ms`)),
                    MEMBER_PAGE_DEADLINE_MS
                )
            }),
        ]).finally(() => clearTimeout(deadline))
        const ids = result.rows.map((row) => row.person_id)
        return {
            ids,
            cursor: ids.length > 0 ? ids[ids.length - 1] : cursor,
            has_more: ids.length === pageSize,
        }
    }
}
