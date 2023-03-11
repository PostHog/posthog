import { DateTime } from 'luxon'
import { Client } from 'pg'

import { EventDefinitionType, EventPropertyType, Person, RawPerson } from '../../src/types'

let postgres: Client

beforeAll(async () => {
    postgres = new Client({
        connectionString: process.env.DATABASE_URL,
    })

    await postgres.connect()
})

afterAll(async () => {
    await postgres.end()
})

export const fetchPostgresPersons = async (teamId: number) => {
    return await postgres.query('SELECT * FROM posthog_person WHERE team_id = $1 ORDER BY id', [teamId]).then((res) =>
        res.rows.map(
            // NOTE: to maintain compatibility with the tests prior to
            // introducing these functions, we need to transform the response a
            // little.
            (rawPerson: RawPerson) =>
                ({
                    ...rawPerson,
                    created_at: DateTime.fromISO(rawPerson.created_at).toUTC(),
                    version: Number(rawPerson.version || 0),
                } as Person)
        )
    )
}

export const fetchEventDefinitions = async (teamId: number) => {
    return await postgres
        .query(
            `
                SELECT * FROM posthog_eventdefinition
                WHERE team_id = $1
                -- Order by something that gives a deterministic order. Note
                -- that this is a unique index.
                ORDER BY (team_id, name)
            `,
            [teamId]
        )
        .then((res) => res.rows as EventDefinitionType[])
}

export const fetchEventProperties = async (teamId: number) => {
    return await postgres
        .query(
            `
                SELECT * FROM posthog_eventproperty
                WHERE team_id = $1
                -- Order by something that gives a deterministic order. Note
                -- that this is a unique index.
                ORDER BY (team_id, event, property)
            `,
            [teamId]
        )
        .then((res) => res.rows as EventPropertyType[])
}

export const fetchPropertyDefinitions = async (teamId: number) => {
    return await postgres
        .query(
            `
                SELECT * FROM posthog_propertydefinition
                WHERE team_id = $1
                -- Order by something that gives a deterministic order. Note
                -- that this is a unique index.
                ORDER BY (team_id, name, type, coalesce(group_type_index, -1))
            `,
            [teamId]
        )
        .then((res) => res.rows)
}

export const fetchDistinctIdValues = async (personId: number) => {
    return await postgres
        .query(
            `
            SELECT distinct_id FROM posthog_persondistinctid 
            WHERE person_id=$1 ORDER BY id
            `,
            [personId]
        )
        .then((res) => res.rows.map((row) => row.distinct_id as string))
}

export const fetchDistinctIds = async (teamId: number, personId: number) => {
    return await postgres
        .query(
            `
            SELECT distinct_id FROM posthog_persondistinctid
            WHERE team_id = $1
            AND person_id = $2
            ORDER BY person_id, id DESC
            `,
            [teamId, personId]
        )
        .then((res) => res.rows.map((row) => row.distinct_id as string))
}

export const disablePlugin = async (pluginConfigId: number) => {
    await postgres.query('UPDATE posthog_pluginconfig SET enabled = FALSE WHERE id = $1', [pluginConfigId])
}
