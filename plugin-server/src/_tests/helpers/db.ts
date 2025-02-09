import { DateTime } from 'luxon'

import { toPerson } from '../../ingestion/event-pipeline-runner/utils/persons-db'
import {
    ClickHousePerson,
    ClickHousePersonDistinctId2,
    Database,
    Group,
    GroupTypeIndex,
    Hub,
    InternalPerson,
    PersonDistinctId,
    RawGroup,
    RawPerson,
    TeamId,
} from '../../types'
import { PostgresUse, TransactionClient } from '../../utils/postgres'
import { escapeClickHouseString } from '../../utils/utils'
import { clickhouseQuery } from './clickhouse'

export class DBHelpers {
    constructor(private hub: Hub) {}

    public async fetchPersons(database?: Database.Postgres): Promise<InternalPerson[]>
    public async fetchPersons(database: Database.ClickHouse): Promise<ClickHousePerson[]>
    public async fetchPersons(database: Database = Database.Postgres): Promise<InternalPerson[] | ClickHousePerson[]> {
        if (database === Database.ClickHouse) {
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
        } else if (database === Database.Postgres) {
            return await this.hub.postgres
                .query<RawPerson>(PostgresUse.COMMON_WRITE, 'SELECT * FROM posthog_person', undefined, 'fetchPersons')
                .then(({ rows }) => rows.map(toPerson))
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
    }

    public async fetchDistinctIds(person: InternalPerson, database?: Database.Postgres): Promise<PersonDistinctId[]>
    public async fetchDistinctIds(
        person: InternalPerson,
        database: Database.ClickHouse
    ): Promise<ClickHousePersonDistinctId2[]>
    public async fetchDistinctIds(
        person: InternalPerson,
        database: Database = Database.Postgres
    ): Promise<PersonDistinctId[] | ClickHousePersonDistinctId2[]> {
        if (database === Database.ClickHouse) {
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
        } else if (database === Database.Postgres) {
            const result = await this.hub.postgres.query(
                PostgresUse.COMMON_WRITE, // used in tests only
                'SELECT * FROM posthog_persondistinctid WHERE person_id=$1 AND team_id=$2 ORDER BY id',
                [person.id, person.team_id],
                'fetchDistinctIds'
            )
            return result.rows as PersonDistinctId[]
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
    }

    public async fetchDistinctIdValues(
        person: InternalPerson,
        database: Database = Database.Postgres
    ): Promise<string[]> {
        const personDistinctIds = await this.fetchDistinctIds(person, database as any)
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
}
