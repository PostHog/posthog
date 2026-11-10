import { DateTime } from 'luxon'

import { InternalPerson, RawPerson } from '@posthog/node-common/types'
import { PostgresRouter, PostgresUse } from '@posthog/node-common/utils/db/postgres'

import { PERSON_COLUMNS } from '~/persons/repositories/postgres-person-repository'

export async function fetchPostgresPersons(postgres: PostgresRouter, teamId: number) {
    // Live persons only, matching production reads: in tombstone mode a merged-away
    // source keeps its row with is_deleted = true.
    const query = `SELECT ${PERSON_COLUMNS} FROM posthog_person WHERE team_id = ${teamId} AND is_deleted = false ORDER BY id`
    return (await postgres.query(PostgresUse.PERSONS_READ, query, undefined, 'persons')).rows.map(
        // NOTE: we map to update some values here to maintain
        // compatibility with `hub.fetchPersons`.
        // TODO: remove unnecessary property translation operation.
        (rawPerson: RawPerson) =>
            ({
                ...rawPerson,
                created_at: DateTime.fromISO(rawPerson.created_at).toUTC(),
                version: Number(rawPerson.version || 0),
                last_seen_at: rawPerson.last_seen_at ? DateTime.fromISO(rawPerson.last_seen_at).toUTC() : null,
            }) as InternalPerson
    )
}

export async function fetchPostgresDistinctIdsForPerson(postgres: PostgresRouter, personId: string): Promise<string[]> {
    const query = `SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = ${personId} ORDER BY id`
    return (await postgres.query(PostgresUse.PERSONS_READ, query, undefined, 'distinctIds')).rows.map(
        (row: { distinct_id: string }) => row.distinct_id
    )
}
