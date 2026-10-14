import { KAFKA_COHORT_MEMBERSHIP_CHANGED } from '~/common/config/kafka-topics'
import { KafkaProducer } from '~/common/kafka/producer'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { membershipChangeMessage } from './membership-change-message'

/**
 * The `origin` of the changes a backfill publishes. The membership consumer skips these: each one
 * repeats a row that is already in Postgres.
 */
export const BACKFILL_ORIGIN = 'backfill'

/**
 * The version a backfill publishes for a row that never carried one. ClickHouse stores a change
 * without `last_updated` at the epoch, its column default, so this matches what a live change
 * without a version would have written.
 */
const VERSIONLESS_BACKFILL_VERSION = '1970-01-01 00:00:00.000000'

type MemberRow = { id: string; team_id: string; cohort_id: string; person_id: string; version: string }

export type MembershipBackfillOptions = {
    /** Null copies every team. */
    teamId: number | null
    batchSize: number
    /** A pause between pages, to keep the read load off the flags lookups that share this database. */
    pauseMs: number
}

/**
 * Publishes every current member in the Postgres `cohort_membership` table to the membership topic.
 *
 * The ClickHouse copy of the table reads that topic from the moment its table was created. Members
 * who entered before then reach it only through this backfill. Each change carries the row's
 * version, so a later live change or sweep for the same person outranks it in ClickHouse. A rerun
 * publishes the same rows again and changes nothing.
 *
 * Rows with `in_cohort = false` are not published, because ClickHouse reads a missing row as not
 * a member.
 */
export class CohortMembershipBackfill {
    constructor(
        private postgres: PostgresRouter,
        private producer: KafkaProducer
    ) {}

    /** Returns the number of members published. */
    public async run(options: MembershipBackfillOptions): Promise<number> {
        let published = 0
        let cursorId = '0'

        for (;;) {
            const page = await this.readPage(options, cursorId)
            if (page.length === 0) {
                return published
            }

            await this.producer.queueMessages({
                topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
                messages: page.map((row) =>
                    membershipChangeMessage({
                        teamId: Number(row.team_id),
                        cohortId: Number(row.cohort_id),
                        personId: row.person_id,
                        status: 'entered',
                        version: row.version,
                        origin: BACKFILL_ORIGIN,
                    })
                ),
            })

            published += page.length
            cursorId = page[page.length - 1].id
            logger.info('Published a page of cohort members for the ClickHouse backfill', {
                published,
                cursor_id: cursorId,
            })

            if (options.pauseMs > 0) {
                await new Promise((resolve) => setTimeout(resolve, options.pauseMs))
            }
        }
    }

    private async readPage(options: MembershipBackfillOptions, cursorId: string): Promise<MemberRow[]> {
        const teamFilter = options.teamId === null ? '' : 'AND team_id = $3'
        const values =
            options.teamId === null ? [cursorId, options.batchSize] : [cursorId, options.batchSize, options.teamId]

        const result = await this.postgres.query<MemberRow>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                SELECT id, team_id, cohort_id, person_id,
                       COALESCE(to_char(version, 'YYYY-MM-DD HH24:MI:SS.US'), '${VERSIONLESS_BACKFILL_VERSION}') AS version
                FROM cohort_membership
                WHERE in_cohort AND id > $1::bigint ${teamFilter}
                ORDER BY id
                LIMIT $2
            `,
            values,
            'readCohortMembershipBackfillPage'
        )

        return result.rows
    }
}
