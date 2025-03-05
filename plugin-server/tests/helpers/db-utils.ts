import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import {
    ClickHouseEvent,
    ClickhouseGroup,
    ClickHousePerson,
    ClickHousePersonDistinctId2,
    DeadLetterQueueEvent,
    Group,
    GroupTypeIndex,
    Hub,
    InternalPerson,
    PersonDistinctId,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    RawClickHouseEvent,
    RawGroup,
    RawPerson,
    TeamId,
} from '../../src/types'
import { toPerson } from '../../src/utils/db/db'
import { PostgresUse, TransactionClient } from '../../src/utils/db/postgres'
import { clickHouseTimestampToDateTime, escapeClickHouseString, RaceConditionError } from '../../src/utils/utils'
import { clickhouseQuery } from './clickhouse'

export enum Database {
    ClickHouse = 'clickhouse',
    Postgres = 'postgres',
}

export function parseRawClickHouseEvent(rawEvent: RawClickHouseEvent): ClickHouseEvent {
    return {
        ...rawEvent,
        timestamp: clickHouseTimestampToDateTime(rawEvent.timestamp),
        created_at: clickHouseTimestampToDateTime(rawEvent.created_at),
        properties: rawEvent.properties ? JSON.parse(rawEvent.properties) : {},
        elements_chain: rawEvent.elements_chain ? (rawEvent.elements_chain as any) : null,
        person_created_at: rawEvent.person_created_at
            ? clickHouseTimestampToDateTime(rawEvent.person_created_at)
            : null,
        person_properties: rawEvent.person_properties ? JSON.parse(rawEvent.person_properties) : {},
        group0_properties: rawEvent.group0_properties ? JSON.parse(rawEvent.group0_properties) : {},
        group1_properties: rawEvent.group1_properties ? JSON.parse(rawEvent.group1_properties) : {},
        group2_properties: rawEvent.group2_properties ? JSON.parse(rawEvent.group2_properties) : {},
        group3_properties: rawEvent.group3_properties ? JSON.parse(rawEvent.group3_properties) : {},
        group4_properties: rawEvent.group4_properties ? JSON.parse(rawEvent.group4_properties) : {},
        group0_created_at: rawEvent.group0_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group0_created_at)
            : null,
        group1_created_at: rawEvent.group1_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group1_created_at)
            : null,
        group2_created_at: rawEvent.group2_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group2_created_at)
            : null,
        group3_created_at: rawEvent.group3_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group3_created_at)
            : null,
        group4_created_at: rawEvent.group4_created_at
            ? clickHouseTimestampToDateTime(rawEvent.group4_created_at)
            : null,
    }
}

export class DBHelpers {
    constructor(private hub: Hub) {}

    public async fetchPersonsFromPostgres(): Promise<InternalPerson[]> {
        return await this.hub.postgres
            .query<RawPerson>(PostgresUse.COMMON_WRITE, 'SELECT * FROM posthog_person', undefined, 'fetchPersons')
            .then(({ rows }) => rows.map(toPerson))
    }

    public async fetchPersonsFromClickhouse(): Promise<ClickHousePerson[]> {
        const query = `
            SELECT id, team_id, is_identified, ts as _timestamp, properties, created_at, is_del as is_deleted, _offset
            FROM (
                SELECT id,
                    team_id,
                    max(is_identified) as is_identified,
                    max(_timestamp) as ts,
                    argMax(properties, _timestamp) as properties,
                    argMin(created_at, _timestamp) as created_at,
                    max(is_deleted) as is_del,
                    argMax(_offset, _timestamp) as _offset
                FROM person
                FINAL
                GROUP BY team_id, id
                HAVING max(is_deleted)=0
            )
            `
        return (await clickhouseQuery(query)).data.map((row) => {
            const { 'person_max._timestamp': _discard1, 'person_max.id': _discard2, ...rest } = row
            return rest
        }) as ClickHousePerson[]
    }

    public async fetchDistinctIdsFromPostgres(person: InternalPerson): Promise<PersonDistinctId[]> {
        const result = await this.hub.postgres.query(
            PostgresUse.COMMON_WRITE, // used in tests only
            'SELECT * FROM posthog_persondistinctid WHERE person_id=$1 AND team_id=$2 ORDER BY id',
            [person.id, person.team_id],
            'fetchDistinctIds'
        )
        return result.rows as PersonDistinctId[]
    }

    public async fetchDistinctIdsFromClickhouse(person: InternalPerson): Promise<ClickHousePersonDistinctId2[]> {
        return (
            await clickhouseQuery(
                `
                    SELECT *
                    FROM person_distinct_id2
                    FINAL
                    WHERE person_id='${escapeClickHouseString(person.uuid)}'
                      AND team_id='${person.team_id}'
                      AND is_deleted=0
                    ORDER BY _offset`
            )
        ).data as ClickHousePersonDistinctId2[]
    }

    public async fetchDistinctIdsValuesFromPostgres(person: InternalPerson): Promise<string[]> {
        const personDistinctIds = await this.fetchDistinctIdsFromPostgres(person)
        return personDistinctIds.map((pdi) => pdi.distinct_id)
    }

    public async fetchDistinctIdsValuesFromClickhouse(person: InternalPerson): Promise<string[]> {
        const personDistinctIds = await this.fetchDistinctIdsFromClickhouse(person)
        return personDistinctIds.map((pdi) => pdi.distinct_id)
    }

    public async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        tx?: TransactionClient,
        options: { forUpdate?: boolean } = {}
    ): Promise<Group | undefined> {
        let queryString = `SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3`

        if (options.forUpdate) {
            queryString = queryString.concat(` FOR UPDATE`)
        }

        const selectResult = await this.hub.postgres.query(
            tx ?? PostgresUse.COMMON_WRITE,
            queryString,
            [teamId, groupTypeIndex, groupKey],
            'fetchGroup'
        )

        if (selectResult.rows.length > 0) {
            const rawGroup: RawGroup = selectResult.rows[0]
            return {
                ...rawGroup,
                created_at: DateTime.fromISO(rawGroup.created_at).toUTC(),
                version: Number(rawGroup.version || 0),
            }
        }
    }

    // Event (NOTE: not a Django model, stored in ClickHouse table `events`)

    public async fetchEvents(): Promise<ClickHouseEvent[]> {
        const queryResult = await clickhouseQuery<RawClickHouseEvent>(`SELECT * FROM events ORDER BY timestamp ASC`)
        return queryResult.data.map(parseRawClickHouseEvent)
    }

    public async fetchDeadLetterQueueEvents(): Promise<DeadLetterQueueEvent[]> {
        const result = await clickhouseQuery(`SELECT * FROM events_dead_letter_queue ORDER BY _timestamp ASC`)
        const events = result.data as DeadLetterQueueEvent[]
        return events
    }

    // Used in tests
    public async fetchClickhouseGroups(): Promise<ClickhouseGroup[]> {
        const query = `
        SELECT group_type_index, group_key, created_at, team_id, group_properties FROM groups FINAL
        `
        return (await clickhouseQuery(query)).data as ClickhouseGroup[]
    }

    public async insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        version: number,
        tx?: TransactionClient
    ): Promise<void> {
        const result = await this.hub.postgres.query(
            tx ?? PostgresUse.COMMON_WRITE,
            `
            INSERT INTO posthog_group (team_id, group_key, group_type_index, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (team_id, group_key, group_type_index) DO NOTHING
            RETURNING version
            `,
            [
                teamId,
                groupKey,
                groupTypeIndex,
                JSON.stringify(groupProperties),
                createdAt.toISO(),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
                version,
            ],
            'upsertGroup'
        )

        if (result.rows.length === 0) {
            throw new RaceConditionError('Parallel posthog_group inserts, retry')
        }
    }
}
