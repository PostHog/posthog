import { DateTime } from 'luxon'

import { InternalPerson, PersonDistinctId, PersonUpdateFields, RawPerson, Team } from '~/types'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'

export const TEST_TIMESTAMP = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

export async function getFirstTeam(postgres: PostgresRouter): Promise<Team> {
    const teams = await postgres.query(
        PostgresUse.COMMON_WRITE,
        'SELECT * FROM posthog_team LIMIT 1',
        [],
        'getFirstTeam'
    )
    return teams.rows[0]
}

/**
 * Testing utilities for person-related database operations.
 * These methods are only used in tests and should not be used in production code.
 */

export async function fetchPersons(postgres: PostgresRouter): Promise<InternalPerson[]> {
    return await postgres
        .query<RawPerson>(PostgresUse.PERSONS_WRITE, 'SELECT * FROM posthog_person', undefined, 'fetchPersons')
        .then(({ rows }) => rows.map(toPerson))
}

export async function fetchDistinctIds(postgres: PostgresRouter, person: InternalPerson): Promise<PersonDistinctId[]> {
    const result = await postgres.query(
        PostgresUse.PERSONS_WRITE, // used in tests only
        'SELECT * FROM posthog_persondistinctid WHERE person_id=$1 AND team_id=$2 ORDER BY id',
        [person.id, person.team_id],
        'fetchDistinctIds'
    )
    return result.rows as PersonDistinctId[]
}

export async function fetchDistinctIdValues(postgres: PostgresRouter, person: InternalPerson): Promise<string[]> {
    const personDistinctIds = await fetchDistinctIds(postgres, person)
    return personDistinctIds.map((pdi) => pdi.distinct_id)
}

function toPerson(row: RawPerson): InternalPerson {
    return {
        ...row,
        id: String(row.id),
        created_at: DateTime.fromISO(row.created_at).toUTC(),
        version: Number(row.version || 0),
    }
}

/**
 * Helper to create PersonUpdateFields for tests with all required fields.
 * Pass partial updates and it will fill in defaults from the person object.
 */
export function createPersonUpdateFields(
    person: InternalPerson,
    updates: Partial<PersonUpdateFields>
): PersonUpdateFields {
    return {
        properties: updates.properties ?? person.properties,
        properties_last_updated_at: updates.properties_last_updated_at ?? person.properties_last_updated_at,
        properties_last_operation: updates.properties_last_operation ?? person.properties_last_operation,
        is_identified: updates.is_identified ?? person.is_identified,
        created_at: updates.created_at ?? person.created_at,
        ...(updates.version !== undefined && { version: updates.version }),
    }
}
