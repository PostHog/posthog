import { DateTime } from 'luxon'
import { QueryResult } from 'pg'
import { Counter } from 'prom-client'

import { KAFKA_PERSON_DISTINCT_ID } from '../../../config/kafka-topics'
import { KafkaProducerWrapper, TopicMessage } from '../../../kafka/producer'
import {
    InternalPerson,
    PersonDistinctId,
    Properties,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    RawPerson,
    Team,
} from '../../../types'
import { PostgresRouter, PostgresUse, TransactionClient } from '../../../utils/postgres'
import { status } from '../../../utils/status'
import { NoRowsUpdatedError, RaceConditionError, sanitizeSqlIdentifier } from '../../../utils/utils'
import { generateKafkaPersonUpdateMessage, sanitizeJsonbValue, unparsePersonPartial } from './utils'

export const personUpdateVersionMismatchCounter = new Counter({
    name: 'person_update_version_mismatch',
    help: 'Person update version mismatch',
})

export const toPerson = (row: RawPerson): InternalPerson => {
    return {
        ...row,
        created_at: DateTime.fromISO(row.created_at).toUTC(),
        version: Number(row.version || 0),
    }
}

/** The recommended way of accessing the database. */
export class PersonsDB {
    constructor(private postgres: PostgresRouter, private kafkaProducer: KafkaProducerWrapper) {}

    // These are all methods to with persons

    private toPerson(row: RawPerson): InternalPerson {
        return toPerson(row)
    }

    public async fetchPerson(
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
            options.useReadReplica ? PostgresUse.COMMON_READ : PostgresUse.COMMON_WRITE,
            queryString,
            values,
            'fetchPerson'
        )

        if (rows.length > 0) {
            return this.toPerson(rows[0])
        }
    }

    public async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        distinctIds?: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<InternalPerson> {
        distinctIds ||= []

        for (const distinctId of distinctIds) {
            distinctId.version ||= 0
        }

        // The Person is being created, and so we can hardcode version 0!
        const personVersion = 0

        const { rows } = await this.postgres.query<RawPerson>(
            tx ?? PostgresUse.COMMON_WRITE,
            `WITH inserted_person AS (
                    INSERT INTO posthog_person (
                        created_at, properties, properties_last_updated_at,
                        properties_last_operation, team_id, is_user_id, is_identified, uuid, version
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING *
                )` +
                distinctIds
                    .map(
                        // NOTE: Keep this in sync with the posthog_persondistinctid INSERT in
                        // `addDistinctIdPooled`
                        (_, index) => `, distinct_id_${index} AS (
                        INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                        VALUES (
                            $${11 + index + distinctIds!.length - 1},
                            (SELECT id FROM inserted_person),
                            $5,
                            $${10 + index})
                        )`
                    )
                    .join('') +
                `SELECT * FROM inserted_person;`,
            [
                createdAt.toISO(),
                sanitizeJsonbValue(properties),
                sanitizeJsonbValue(propertiesLastUpdatedAt),
                sanitizeJsonbValue(propertiesLastOperation),
                teamId,
                isUserId,
                isIdentified,
                uuid,
                personVersion,
                // The copy and reverse here is to maintain compatability with pre-existing code
                // and tests. Postgres appears to assign IDs in reverse order of the INSERTs in the
                // CTEs above, so we need to reverse the distinctIds to match the old behavior where
                // we would do a round trip for each INSERT. We shouldn't actually depend on the
                // `id` column of distinct_ids, so this is just a simple way to keeps tests exactly
                // the same and prove behavior is the same as before.
                ...distinctIds
                    .slice()
                    .reverse()
                    .map(({ version }) => version),
                ...distinctIds
                    .slice()
                    .reverse()
                    .map(({ distinctId }) => distinctId),
            ],
            'insertPerson'
        )
        const person = this.toPerson(rows[0])

        const kafkaMessages = [generateKafkaPersonUpdateMessage(person)]

        for (const distinctId of distinctIds) {
            kafkaMessages.push({
                topic: KAFKA_PERSON_DISTINCT_ID,
                messages: [
                    {
                        value: JSON.stringify({
                            person_id: person.uuid,
                            team_id: teamId,
                            distinct_id: distinctId.distinctId,
                            version: distinctId.version,
                            is_deleted: 0,
                        }),
                    },
                ],
            })
        }

        await this.kafkaProducer.queueMessages(kafkaMessages)
        return person
    }

    // Currently in use, but there are various problems with this function
    public async updatePersonDeprecated(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[]]> {
        let versionString = 'COALESCE(version, 0)::numeric + 1'
        if (update.version) {
            versionString = update.version.toString()
            delete update['version']
        }

        const updateValues = Object.values(unparsePersonPartial(update))

        // short circuit if there are no updates to be made
        if (updateValues.length === 0) {
            return [person, []]
        }

        const values = [...updateValues, person.id].map(sanitizeJsonbValue)

        // Potentially overriding values badly if there was an update to the person after computing updateValues above
        const queryString = `UPDATE posthog_person SET version = ${versionString}, ${Object.keys(update).map(
            (field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`
        )} WHERE id = $${Object.values(update).length + 1}
        RETURNING *`

        const { rows } = await this.postgres.query<RawPerson>(
            tx ?? PostgresUse.COMMON_WRITE,
            queryString,
            values,
            'updatePerson'
        )
        if (rows.length == 0) {
            throw new NoRowsUpdatedError(
                `Person with team_id="${person.team_id}" and uuid="${person.uuid} couldn't be updated`
            )
        }
        const updatedPerson = this.toPerson(rows[0])

        // Track the disparity between the version on the database and the version of the person we have in memory
        // Without races, the returned person (updatedPerson) should have a version that's only +1 the person in memory
        const versionDisparity = updatedPerson.version - person.version - 1
        if (versionDisparity > 0) {
            personUpdateVersionMismatchCounter.inc()
        }

        const kafkaMessage = generateKafkaPersonUpdateMessage(updatedPerson)

        status.debug(
            '🧑‍🦰',
            `Updated person ${updatedPerson.uuid} of team ${updatedPerson.team_id} to version ${updatedPerson.version}.`
        )

        return [updatedPerson, [kafkaMessage]]
    }

    public async deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]> {
        const { rows } = await this.postgres.query<{ version: string }>(
            tx ?? PostgresUse.COMMON_WRITE,
            'DELETE FROM posthog_person WHERE team_id = $1 AND id = $2 RETURNING version',
            [person.team_id, person.id],
            'deletePerson'
        )

        let kafkaMessages: TopicMessage[] = []

        if (rows.length > 0) {
            const [row] = rows
            kafkaMessages = [generateKafkaPersonUpdateMessage({ ...person, version: Number(row.version || 0) }, true)]
        }
        return kafkaMessages
    }

    // PersonDistinctId
    // testutil
    // public async fetchDistinctIds(person: InternalPerson, database?: Database.Postgres): Promise<PersonDistinctId[]>
    // public async fetchDistinctIds(
    //     person: InternalPerson,
    //     database: Database.ClickHouse
    // ): Promise<ClickHousePersonDistinctId2[]>
    // public async fetchDistinctIds(
    //     person: InternalPerson,
    //     database: Database = Database.Postgres
    // ): Promise<PersonDistinctId[] | ClickHousePersonDistinctId2[]> {
    //     if (database === Database.ClickHouse) {
    //         return (
    //             await this.clickhouseQuery(
    //                 `
    //                     SELECT *
    //                     FROM person_distinct_id2
    //                     FINAL
    //                     WHERE person_id='${escapeClickHouseString(person.uuid)}'
    //                       AND team_id='${person.team_id}'
    //                       AND is_deleted=0
    //                     ORDER BY _offset`
    //             )
    //         ).data as ClickHousePersonDistinctId2[]
    //     } else if (database === Database.Postgres) {
    //         const result = await this.postgres.query(
    //             PostgresUse.COMMON_WRITE, // used in tests only
    //             'SELECT * FROM posthog_persondistinctid WHERE person_id=$1 AND team_id=$2 ORDER BY id',
    //             [person.id, person.team_id],
    //             'fetchDistinctIds'
    //         )
    //         return result.rows as PersonDistinctId[]
    //     } else {
    //         throw new Error(`Can't fetch persons for database: ${database}`)
    //     }
    // }

    // Only used in tests
    // public async fetchDistinctIdValues(
    //     person: InternalPerson,
    //     database: Database = Database.Postgres
    // ): Promise<string[]> {
    //     const personDistinctIds = await this.fetchDistinctIds(person, database as any)
    //     return personDistinctIds.map((pdi) => pdi.distinct_id)
    // }

    public async addPersonlessDistinctId(teamId: number, distinctId: string): Promise<boolean> {
        const result = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `
                INSERT INTO posthog_personlessdistinctid (team_id, distinct_id, is_merged, created_at)
                VALUES ($1, $2, false, now())
                ON CONFLICT (team_id, distinct_id) DO NOTHING
                RETURNING is_merged
            `,
            [teamId, distinctId],
            'addPersonlessDistinctId'
        )

        if (result.rows.length === 1) {
            return result.rows[0]['is_merged']
        }

        // ON CONFLICT ... DO NOTHING won't give us our RETURNING, so we have to do another SELECT
        const existingResult = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `
                SELECT is_merged
                FROM posthog_personlessdistinctid
                WHERE team_id = $1 AND distinct_id = $2
            `,
            [teamId, distinctId],
            'addPersonlessDistinctId'
        )

        return existingResult.rows[0]['is_merged']
    }

    public async addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        const result = await this.postgres.query(
            tx ?? PostgresUse.COMMON_WRITE,
            `
                INSERT INTO posthog_personlessdistinctid (team_id, distinct_id, is_merged, created_at)
                VALUES ($1, $2, true, now())
                ON CONFLICT (team_id, distinct_id) DO UPDATE
                SET is_merged = true
                RETURNING (xmax = 0) AS inserted
            `,
            [teamId, distinctId],
            'addPersonlessDistinctIdForMerge'
        )

        return result.rows[0].inserted
    }

    public async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<void> {
        const kafkaMessages = await this.addDistinctIdPooled(person, distinctId, version, tx)
        if (kafkaMessages.length) {
            await this.kafkaProducer.queueMessages(kafkaMessages)
        }
    }

    private async addDistinctIdPooled(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const insertResult = await this.postgres.query(
            tx ?? PostgresUse.COMMON_WRITE,
            // NOTE: Keep this in sync with the posthog_persondistinctid INSERT in `createPerson`
            'INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version) VALUES ($1, $2, $3, $4) RETURNING *',
            [distinctId, person.id, person.team_id, version],
            'addDistinctIdPooled'
        )

        const { id, ...personDistinctIdCreated } = insertResult.rows[0] as PersonDistinctId
        const messages = [
            {
                topic: KAFKA_PERSON_DISTINCT_ID,
                messages: [
                    {
                        value: JSON.stringify({
                            ...personDistinctIdCreated,
                            version,
                            person_id: person.uuid,
                            is_deleted: 0,
                        }),
                    },
                ],
            },
        ]

        return messages
    }

    public async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        let movedDistinctIdResult: QueryResult<any> | null = null
        try {
            movedDistinctIdResult = await this.postgres.query(
                tx ?? PostgresUse.COMMON_WRITE,
                `
                    UPDATE posthog_persondistinctid
                    SET person_id = $1, version = COALESCE(version, 0)::numeric + 1
                    WHERE person_id = $2
                      AND team_id = $3
                    RETURNING *
                `,
                [target.id, source.id, target.team_id],
                'updateDistinctIdPerson'
            )
        } catch (error) {
            if (
                (error as Error).message.includes(
                    'insert or update on table "posthog_persondistinctid" violates foreign key constraint'
                )
            ) {
                // this is caused by a race condition where the _target_ person was deleted after fetching but
                // before the update query ran and will trigger a retry with updated persons
                throw new RaceConditionError(
                    'Failed trying to move distinct IDs because target person no longer exists.'
                )
            }

            throw error
        }

        // this is caused by a race condition where the _source_ person was deleted after fetching but
        // before the update query ran and will trigger a retry with updated persons
        if (movedDistinctIdResult.rows.length === 0) {
            throw new RaceConditionError(
                `Failed trying to move distinct IDs because the source person no longer exists.`
            )
        }

        const kafkaMessages = []
        for (const row of movedDistinctIdResult.rows) {
            const { id, version: versionStr, ...usefulColumns } = row as PersonDistinctId
            const version = Number(versionStr || 0)
            kafkaMessages.push({
                topic: KAFKA_PERSON_DISTINCT_ID,
                messages: [
                    {
                        value: JSON.stringify({ ...usefulColumns, version, person_id: target.uuid, is_deleted: 0 }),
                    },
                ],
            })
        }
        return kafkaMessages
    }

    public async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void> {
        // When personIDs change, update places depending on a person_id foreign key

        await this.postgres.query(
            tx ?? PostgresUse.COMMON_WRITE,
            // Do two high level things in a single round-trip to the DB.
            //
            // 1. Update cohorts.
            // 2. Update (delete+insert) feature flags.
            //
            // NOTE: Every override is unique for a team-personID-featureFlag combo. In case we run
            // into a conflict we would ideally use the override from most recent personId used, so
            // the user experience is consistent, however that's tricky to figure out this also
            // happens rarely, so we're just going to do the performance optimal thing i.e. do
            // nothing on conflicts, so we keep using the value that the person merged into had
            `WITH cohort_update AS (
                UPDATE posthog_cohortpeople
                SET person_id = $1
                WHERE person_id = $2
                RETURNING person_id
            ),
            deletions AS (
                DELETE FROM posthog_featureflaghashkeyoverride
                WHERE team_id = $3 AND person_id = $2
                RETURNING team_id, person_id, feature_flag_key, hash_key
            )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, $1, feature_flag_key, hash_key
                FROM deletions
                ON CONFLICT DO NOTHING`,
            [targetPersonID, sourcePersonID, teamID],
            'updateCohortAndFeatureFlagsPeople'
        )
    }
}
