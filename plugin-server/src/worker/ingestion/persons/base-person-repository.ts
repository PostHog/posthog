import { DateTime } from 'luxon'

import { InternalPerson, RawPerson } from '../../../types'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { PersonRepository } from './person-repository'

export class BasePersonRepository implements PersonRepository {
    constructor(private postgres: PostgresRouter) {}

    async fetchPerson(
        teamId: number,
        distinctId: string,
        options: { forUpdate?: boolean; useReadReplica?: boolean } = {}
    ): Promise<InternalPerson | undefined> {
        if (options.forUpdate && options.useReadReplica) {
            throw new Error("can't enable both forUpdate and useReadReplica in db::fetchPerson")
        }

        let queryString = `SELECT
                posthog_person.id,
                posthog_person.uuid,
                posthog_person.created_at,
                posthog_person.team_id,
                posthog_person.properties,
                posthog_person.properties_last_updated_at,
                posthog_person.properties_last_operation,
                posthog_person.is_user_id,
                posthog_person.version,
                posthog_person.is_identified
            FROM posthog_person
            JOIN posthog_persondistinctid ON (posthog_persondistinctid.person_id = posthog_person.id)
            WHERE
                posthog_person.team_id = $1
                AND posthog_persondistinctid.team_id = $1
                AND posthog_persondistinctid.distinct_id = $2`
        if (options.forUpdate) {
            // Locks the teamId and distinctId tied to this personId + this person's info
            queryString = queryString.concat(` FOR UPDATE`)
        }
        const values = [teamId, distinctId]

        const { rows } = await this.postgres.query<RawPerson>(
            options.useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
            queryString,
            values,
            'fetchPerson'
        )

        if (rows.length > 0) {
            return this.toPerson(rows[0])
        }
    }

    private toPerson(row: RawPerson): InternalPerson {
        return {
            ...row,
            id: String(row.id),
            created_at: DateTime.fromISO(row.created_at).toUTC(),
            version: Number(row.version || 0),
        }
    }
}
