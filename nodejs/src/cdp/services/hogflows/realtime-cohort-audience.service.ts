import { PoolClient } from 'pg'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

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
        // The resolver heartbeats its job while it waits, so a stalled read would hold the job without
        // ever failing. The deadline turns a stall into an error, which the resolver retries.
        let timer: NodeJS.Timeout | undefined
        let timedOut = false
        const deadline = new Promise<never>((_, reject) => {
            timer = setTimeout(() => {
                timedOut = true
                reject(new Error(`Realtime cohort member page took longer than ${MEMBER_PAGE_DEADLINE_MS}ms`))
            }, MEMBER_PAGE_DEADLINE_MS)
        })

        const checkout = this.postgres.connect(PostgresUse.BEHAVIORAL_COHORTS_RW)
        // A connection that arrives after the deadline goes straight back to the pool.
        void checkout.then(
            (late) => timedOut && late.release(),
            () => undefined
        )

        let client: PoolClient | undefined
        // pg drops the pool's error listener from a checked-out client, and an unhandled 'error'
        // event would crash the process.
        const onClientError = (error: Error): void => {
            logger.warn('🔌', 'Realtime cohort member page connection error', { error: String(error) })
        }
        try {
            client = await Promise.race([checkout, deadline])
            client.on('error', onClientError)
            const ids = await Promise.race([this.readPage(client, cohortTeamId, cohortId, cursor, pageSize), deadline])
            client.removeListener('error', onClientError)
            client.release()
            return {
                ids,
                cursor: ids.length > 0 ? ids[ids.length - 1] : cursor,
                has_more: ids.length === pageSize,
            }
        } catch (error) {
            // Releasing with an error ends the connection. That stops a read that is still running,
            // so a stall can't keep the connection out of the pool.
            client?.release(error instanceof Error ? error : new Error(String(error)))
            throw error
        } finally {
            clearTimeout(timer)
        }
    }

    private async readPage(
        client: PoolClient,
        cohortTeamId: number,
        cohortId: number,
        cursor: string | null,
        pageSize: number
    ): Promise<string[]> {
        const afterCursor = cursor === null ? '' : 'AND person_id > $4::uuid'
        const values: unknown[] = [cohortTeamId, cohortId, pageSize]
        if (cursor !== null) {
            values.push(cursor)
        }
        await client.query('BEGIN')
        await client.query(`SET LOCAL statement_timeout = ${MEMBER_PAGE_TIMEOUT_MS}`)
        const result = await client.query<{ person_id: string }>(
            `
                SELECT person_id
                FROM cohort_membership
                WHERE team_id = $1 AND cohort_id = $2 AND in_cohort ${afterCursor}
                ORDER BY person_id
                LIMIT $3
            `,
            values
        )
        await client.query('COMMIT')
        return result.rows.map((row) => row.person_id)
    }
}
