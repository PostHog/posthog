import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { KAFKA_PERSON_DISTINCT_ID } from '../../../config/kafka-topics'
import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, RawPerson } from '../../../types'
import { PostgresRouter, PostgresUse, TransactionClient } from '../../../utils/db/postgres'
import { generateKafkaPersonUpdateMessage, sanitizeJsonbValue } from '../../../utils/db/utils'
import { PersonRepository } from './person-repository'

export class BasePersonRepository implements PersonRepository {
    constructor(private postgres: PostgresRouter) {}

    private toPerson(row: RawPerson): InternalPerson {
        return {
            ...row,
            id: String(row.id),
            created_at: DateTime.fromISO(row.created_at).toUTC(),
            version: Number(row.version || 0),
        }
    }

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

    async createPerson(
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
    ): Promise<[InternalPerson, TopicMessage[]]> {
        distinctIds ||= []

        for (const distinctId of distinctIds) {
            distinctId.version ||= 0
        }

        // The Person is being created, and so we can hardcode version 0!
        const personVersion = 0

        const { rows } = await this.postgres.query<RawPerson>(
            tx ?? PostgresUse.PERSONS_WRITE,
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
                        // `addDistinctId`
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
            'insertPerson',
            'warn'
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

        return [person, kafkaMessages]
    }
}
