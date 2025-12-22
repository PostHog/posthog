import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import { Properties } from '@posthog/plugin-scaffold'

import { KAFKA_PERSON_DISTINCT_ID } from '../../../../config/kafka-topics'
import { TopicMessage } from '../../../../kafka/producer'
import {
    InternalPerson,
    PersonDistinctId,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    RawPerson,
    Team,
    TeamId,
} from '../../../../types'
import { CreatePersonResult, MoveDistinctIdsResult, PersonPropertiesSize } from '../../../../utils/db/db'
import {
    moveDistinctIdsCountHistogram,
    personPropertiesSizeHistogram,
    personUpdateVersionMismatchCounter,
} from '../../../../utils/db/metrics'
import { PostgresRouter, PostgresUse, TransactionClient } from '../../../../utils/db/postgres'
import { generateKafkaPersonUpdateMessage, sanitizeJsonbValue, unparsePersonPartial } from '../../../../utils/db/utils'
import { logger } from '../../../../utils/logger'
import { NoRowsUpdatedError, sanitizeSqlIdentifier } from '../../../../utils/utils'
import {
    oversizedPersonPropertiesTrimmedCounter,
    personJsonFieldSizeHistogram,
    personPropertiesSizeViolationCounter,
} from '../metrics'
import { canTrimProperty } from '../person-property-utils'
import { PersonUpdate } from '../person-update-batch'
import { InternalPersonWithDistinctId, PersonPropertiesSizeViolationError, PersonRepository } from './person-repository'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { PostgresPersonRepositoryTransaction } from './postgres-person-repository-transaction'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

const DEFAULT_PERSON_PROPERTIES_TRIM_TARGET_BYTES = 512 * 1024
const DEFAULT_PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES = 655360

export interface PostgresPersonRepositoryOptions {
    calculatePropertiesSize: number
    /** Limit used when comparing pg_column_size(properties) to decide whether to remediate */
    personPropertiesDbConstraintLimitBytes: number
    /** Target JSON size (stringified) to trim down to when remediating oversized properties */
    personPropertiesTrimTargetBytes: number
}

const DEFAULT_OPTIONS: PostgresPersonRepositoryOptions = {
    calculatePropertiesSize: 0,
    personPropertiesDbConstraintLimitBytes: DEFAULT_PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES,
    personPropertiesTrimTargetBytes: DEFAULT_PERSON_PROPERTIES_TRIM_TARGET_BYTES,
}

export class PostgresPersonRepository
    implements PersonRepository, RawPostgresPersonRepository, PersonRepositoryTransaction
{
    private options: PostgresPersonRepositoryOptions

    constructor(
        private postgres: PostgresRouter,
        options?: Partial<PostgresPersonRepositoryOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
    }

    private async handleOversizedPersonProperties(
        person: InternalPerson,
        update: PersonUpdateFields,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const currentSize = await this.personPropertiesSize(person.id, person.team_id)

        if (currentSize >= this.options.personPropertiesDbConstraintLimitBytes) {
            try {
                personPropertiesSizeViolationCounter.inc({
                    violation_type: 'existing_record_violates_limit',
                })
                return await this.handleExistingOversizedRecord(person, update, tx)
            } catch (error) {
                logger.warn('Failed to handle previously oversized person record', {
                    team_id: person.team_id,
                    person_id: person.id,
                    violation_type: 'existing_record_violates_limit',
                })

                throw new PersonPropertiesSizeViolationError(
                    `Person properties update failed after trying to trim oversized properties`,
                    person.team_id,
                    person.id
                )
            }
        } else {
            // current record is within limits, reject the write
            personPropertiesSizeViolationCounter.inc({
                violation_type: 'attempt_to_violate_limit',
            })

            logger.warn('Rejecting person properties create/update, exceed size limit', {
                team_id: person.team_id,
                person_id: person.id,
                violation_type: 'attempt_to_violate_limit',
            })

            throw new PersonPropertiesSizeViolationError(
                `Person properties update would exceed size limit`,
                person.team_id,
                person.id
            )
        }
    }

    private async handleExistingOversizedRecord(
        person: InternalPerson,
        update: PersonUpdateFields,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        try {
            const trimmedProperties = this.trimPropertiesToFitSize(
                // NOTE: we exclude the properties in the update and just try to trim the existing properties for simplicity
                // we are throwing data away either way
                person.properties,
                this.options.personPropertiesTrimTargetBytes,
                { teamId: person.team_id, personId: person.id }
            )

            const trimmedUpdate: PersonUpdateFields = {
                ...update,
                properties: trimmedProperties,
            }
            const [updatedPerson, kafkaMessages, versionDisparity] = await this.updatePerson(
                person,
                trimmedUpdate,
                'oversized_properties_remediation',
                tx
            )
            oversizedPersonPropertiesTrimmedCounter.inc({ result: 'success' })
            return [updatedPerson, kafkaMessages, versionDisparity]
        } catch (error) {
            oversizedPersonPropertiesTrimmedCounter.inc({ result: 'failed' })
            logger.error('Failed to handle previously oversized person record', {
                team_id: person.team_id,
                person_id: person.id,
                error,
            })
            throw error
        }
    }

    private isPropertiesSizeConstraintViolation(error: any): boolean {
        return error?.code === '23514' && error?.constraint === 'check_properties_size'
    }

    private toPerson(row: RawPerson): InternalPerson {
        return {
            ...row,
            id: String(row.id),
            created_at: DateTime.fromISO(row.created_at).toUTC(),
            version: Number(row.version || 0),
        }
    }

    private trimPropertiesToFitSize(
        properties: Record<string, any>,
        targetSizeBytes: number,
        context?: { teamId: number; personId: string }
    ): Record<string, any> {
        const trimmedProperties = { ...properties }

        let currentSizeBytes = Buffer.byteLength(JSON.stringify(trimmedProperties), 'utf8')

        if (currentSizeBytes <= targetSizeBytes) {
            return trimmedProperties
        }

        let removedCount = 0
        const propertyKeys = Object.keys(trimmedProperties).sort()

        for (const prop of propertyKeys) {
            if (!canTrimProperty(prop)) {
                continue
            }

            const propertyValue = trimmedProperties[prop]
            const keySize = Buffer.byteLength(JSON.stringify(prop), 'utf8') // includes quotes
            const valueSize = Buffer.byteLength(JSON.stringify(propertyValue), 'utf8')
            // 2 is for the colon and comma. Comma won't be present on last property but we don't care enough to check
            const propertyTotalSize = keySize + valueSize + 2

            delete trimmedProperties[prop]
            removedCount++

            currentSizeBytes -= propertyTotalSize

            if (currentSizeBytes <= targetSizeBytes) {
                break
            }
        }

        const finalSizeBytes = Buffer.byteLength(JSON.stringify(trimmedProperties), 'utf8')

        logger.info('Completed trimming person properties', {
            final_size_bytes: finalSizeBytes,
            estimated_size_bytes: currentSizeBytes,
            target_size_bytes: targetSizeBytes,
            properties_removed: removedCount,
            final_property_count: Object.keys(trimmedProperties).length,
            team_id: context?.teamId,
            person_id: context?.personId,
        })
        return trimmedProperties
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
            JOIN posthog_persondistinctid ON (
                posthog_persondistinctid.person_id = posthog_person.id
                AND posthog_persondistinctid.team_id = posthog_person.team_id
            )
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

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        useReadReplica: boolean = true
    ): Promise<InternalPersonWithDistinctId[]> {
        if (teamPersons.length === 0) {
            return []
        }

        // Deduplicate inputs to avoid duplicate rows in results
        const seen = new Set<string>()
        const uniqueTeamPersons = teamPersons.filter((p) => {
            const key = `${p.teamId}:${p.distinctId}`
            if (seen.has(key)) {
                return false
            }
            seen.add(key)
            return true
        })

        // Use UNNEST with two arrays to keep query structure constant for prepared statement reuse.
        // This is more efficient than building dynamic OR conditions because PostgreSQL can
        // prepare and cache the execution plan regardless of batch size.
        const teamIds = uniqueTeamPersons.map((p) => p.teamId)
        const distinctIds = uniqueTeamPersons.map((p) => p.distinctId)

        const queryString = `SELECT
                posthog_person.id,
                posthog_person.uuid,
                posthog_person.created_at,
                posthog_person.team_id,
                posthog_person.properties,
                posthog_person.properties_last_updated_at,
                posthog_person.properties_last_operation,
                posthog_person.is_user_id,
                posthog_person.version,
                posthog_person.is_identified,
                posthog_persondistinctid.distinct_id
            FROM posthog_person
            JOIN posthog_persondistinctid ON (
                posthog_persondistinctid.person_id = posthog_person.id
                AND posthog_persondistinctid.team_id = posthog_person.team_id
            )
            JOIN UNNEST($1::integer[], $2::text[]) AS batch(team_id, distinct_id)
                ON posthog_persondistinctid.team_id = batch.team_id
                AND posthog_persondistinctid.distinct_id = batch.distinct_id`

        const { rows } = await this.postgres.query<RawPerson & { distinct_id: string }>(
            useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
            queryString,
            [teamIds, distinctIds],
            'fetchPersonsByDistinctIds'
        )

        return rows.map((row) => ({
            ...this.toPerson(row),
            distinct_id: row.distinct_id,
        }))
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
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds: { distinctId: string; version?: number }[] = [],
        tx?: TransactionClient
    ): Promise<CreatePersonResult> {
        const distinctIds = [primaryDistinctId, ...extraDistinctIds]
        for (const distinctId of distinctIds) {
            distinctId.version ||= 0
        }

        // The Person is being created, and so we can hardcode version 0!
        const personVersion = 0

        try {
            const columns = [
                'created_at',
                'properties',
                'properties_last_updated_at',
                'properties_last_operation',
                'team_id',
                'is_user_id',
                'is_identified',
                'uuid',
                'version',
            ]
            const valuePlaceholders = columns.map((_, i) => `$${i + 1}`).join(', ')

            // Sanitize and measure JSON field sizes
            const sanitizedProperties = sanitizeJsonbValue(properties)
            const sanitizedPropertiesLastUpdatedAt = sanitizeJsonbValue(propertiesLastUpdatedAt)
            const sanitizedPropertiesLastOperation = sanitizeJsonbValue(propertiesLastOperation)

            // Record JSON field sizes (using string length as approximation)
            if (typeof sanitizedProperties === 'string') {
                personJsonFieldSizeHistogram
                    .labels({ operation: 'createPerson', field: 'properties' })
                    .observe(sanitizedProperties.length)
            }
            if (typeof sanitizedPropertiesLastUpdatedAt === 'string') {
                personJsonFieldSizeHistogram
                    .labels({ operation: 'createPerson', field: 'properties_last_updated_at' })
                    .observe(sanitizedPropertiesLastUpdatedAt.length)
            }
            if (typeof sanitizedPropertiesLastOperation === 'string') {
                personJsonFieldSizeHistogram
                    .labels({ operation: 'createPerson', field: 'properties_last_operation' })
                    .observe(sanitizedPropertiesLastOperation.length)
            }

            const personParams = [
                createdAt.toISO(),
                sanitizedProperties,
                sanitizedPropertiesLastUpdatedAt,
                sanitizedPropertiesLastOperation,
                teamId,
                isUserId,
                isIdentified,
                uuid,
                personVersion,
            ]

            // Find the actual index of team_id in the personParams array (1-indexed for SQL)
            const teamIdParamIndex = personParams.indexOf(teamId) + 1
            const distinctIdVersionStartIndex = columns.length + 1
            const distinctIdStartIndex = distinctIdVersionStartIndex + distinctIds.length

            const distinctIdsCTE =
                distinctIds.length > 0
                    ? `, distinct_ids AS (
                            INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                            VALUES ${distinctIds
                                .map(
                                    // NOTE: Keep this in sync with the posthog_persondistinctid INSERT in
                                    // `addDistinctId`
                                    (_, index) => `(
                                $${distinctIdStartIndex + index},
                                (SELECT id FROM inserted_person),
                                $${teamIdParamIndex},
                                $${distinctIdVersionStartIndex + index}
                            )`
                                )
                                .join(', ')}
                        )`
                    : ''

            const query =
                `WITH inserted_person AS (
                        INSERT INTO posthog_person (${columns.join(', ')})
                        VALUES (${valuePlaceholders})
                        RETURNING *
                    )` +
                distinctIdsCTE +
                ` SELECT * FROM inserted_person;`

            const { rows } = await this.postgres.query<RawPerson>(
                tx ?? PostgresUse.PERSONS_WRITE,
                query,
                [
                    ...personParams,
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

            return {
                success: true,
                person,
                messages: kafkaMessages,
                created: true,
            }
        } catch (error) {
            // Handle constraint violation - another process created the person concurrently
            if (error instanceof Error && error.message.includes('unique constraint')) {
                // This is not of type CreatePersonResult?
                return {
                    success: false,
                    error: 'CreationConflict',
                    distinctIds: distinctIds.map((d) => d.distinctId),
                }
            }

            if (this.isPropertiesSizeConstraintViolation(error)) {
                // For createPerson, we just log and reject since there's no existing person to update
                personPropertiesSizeViolationCounter.inc({
                    violation_type: 'create_person_size_violation',
                })

                logger.warn('Rejecting person properties create/update, exceeds size limit', {
                    team_id: teamId,
                    person_id: undefined,
                    violation_type: 'create_person_size_violation',
                })

                throw new PersonPropertiesSizeViolationError(
                    `Person properties create would exceed size limit`,
                    teamId,
                    undefined
                )
            }

            // Re-throw other errors
            throw error
        }
    }

    async deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<TopicMessage[]> {
        let rows: { version: string }[] = []
        try {
            const result = await this.postgres.query<{ version: string }>(
                tx ?? PostgresUse.PERSONS_WRITE,
                'DELETE FROM posthog_person WHERE team_id = $1 AND id = $2 RETURNING version',
                [person.team_id, person.id],
                'deletePerson'
            )
            rows = result.rows
        } catch (error) {
            if (error.code === '40P01') {
                // Deadlock detected — assume someone else is deleting and skip.
                logger.warn('🔒', 'Deadlock detected — assume someone else is deleting and skip.', {
                    team_id: person.team_id,
                    person_id: person.id,
                })
            }
            throw error
        }

        let kafkaMessages: TopicMessage[] = []

        if (rows.length > 0) {
            const [row] = rows
            kafkaMessages = [generateKafkaPersonUpdateMessage({ ...person, version: Number(row.version || 0) }, true)]
        }
        return kafkaMessages
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<TopicMessage[]> {
        const insertResult = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            // NOTE: Keep this in sync with the posthog_persondistinctid INSERT in `createPerson`
            'INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version) VALUES ($1, $2, $3, $4) RETURNING *',
            [distinctId, person.id, person.team_id, version],
            'addDistinctId',
            'warn'
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

    async moveDistinctIds(
        source: InternalPerson,
        target: InternalPerson,
        limit?: number,
        tx?: TransactionClient
    ): Promise<MoveDistinctIdsResult> {
        let movedDistinctIdResult: QueryResult<any> | null = null
        try {
            const hasLimit = limit !== undefined
            const query = hasLimit
                ? `
                    WITH rows_to_update AS (
                        SELECT id
                        FROM posthog_persondistinctid
                        WHERE person_id = $2
                          AND team_id = $3
                        ORDER BY id
                        FOR UPDATE SKIP LOCKED
                        LIMIT $4
                    )
                    UPDATE posthog_persondistinctid
                    SET person_id = $1, version = COALESCE(version, 0)::numeric + 1
                    WHERE id IN (SELECT id FROM rows_to_update)
                    RETURNING *
                `
                : `
                    UPDATE posthog_persondistinctid
                    SET person_id = $1, version = COALESCE(version, 0)::numeric + 1
                    WHERE person_id = $2
                      AND team_id = $3
                    RETURNING *
                `

            const values = [target.id, source.id, target.team_id]
            if (hasLimit) {
                values.push(limit)
            }

            movedDistinctIdResult = await this.postgres.query(
                tx ?? PostgresUse.PERSONS_WRITE,
                query,
                values,
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
                logger.warn('😵', 'Target person no longer exists', {
                    team_id: target.team_id,
                    person_id: target.id,
                })
                // Track 0 moved IDs for failed merges
                moveDistinctIdsCountHistogram.observe(0)
                return {
                    success: false,
                    error: 'TargetNotFound',
                }
            }

            throw error
        }

        // this is caused by a race condition where the _source_ person was deleted after fetching but
        // before the update query ran and will trigger a retry with updated persons
        if (movedDistinctIdResult.rows.length === 0) {
            logger.warn('😵', 'Source person no longer exists', {
                team_id: source.team_id,
                person_id: source.id,
            })
            // Track 0 moved IDs for failed merges
            moveDistinctIdsCountHistogram.observe(0)
            return {
                success: false,
                error: 'SourceNotFound',
            }
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

        // Track the number of distinct IDs moved in this merge operation
        moveDistinctIdsCountHistogram.observe(movedDistinctIdResult.rows.length)

        return {
            success: true,
            messages: kafkaMessages,
            distinctIdsMoved: movedDistinctIdResult.rows.map((row) => row.distinct_id),
        }
    }

    async fetchPersonDistinctIds(person: InternalPerson, limit?: number, tx?: TransactionClient): Promise<string[]> {
        const hasLimit = limit !== undefined
        const queryString = hasLimit
            ? `
                SELECT distinct_id
                FROM posthog_persondistinctid
                WHERE person_id = $1 AND team_id = $2
                ORDER BY id
                LIMIT $3
            `
            : `
                SELECT distinct_id
                FROM posthog_persondistinctid
                WHERE person_id = $1 AND team_id = $2
                ORDER BY id
            `

        const values = [person.id, person.team_id]
        if (hasLimit) {
            values.push(limit)
        }

        const { rows } = await this.postgres.query<{ distinct_id: string }>(
            tx ?? PostgresUse.PERSONS_WRITE,
            queryString,
            values,
            'fetchPersonDistinctIds'
        )

        return rows.map((row) => row.distinct_id)
    }

    async addPersonlessDistinctId(teamId: number, distinctId: string, tx?: TransactionClient): Promise<boolean> {
        // Use ON CONFLICT DO UPDATE with a no-op to always get the RETURNING clause.
        // This eliminates the need for a fallback SELECT query on conflict (~10k queries/min saved).
        // The no-op update on is_merged (not indexed) results in a HOT update, which is very cheap:
        // - No index maintenance required
        // - Creates a dead tuple that gets cleaned up by autovacuum
        const result = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            `
                INSERT INTO posthog_personlessdistinctid (team_id, distinct_id, is_merged, created_at)
                VALUES ($1, $2, false, now())
                ON CONFLICT (team_id, distinct_id) DO UPDATE
                SET is_merged = posthog_personlessdistinctid.is_merged
                RETURNING is_merged
            `,
            [teamId, distinctId],
            'addPersonlessDistinctId'
        )

        return result.rows[0]['is_merged']
    }

    async addPersonlessDistinctIdForMerge(
        teamId: number,
        distinctId: string,
        tx?: TransactionClient
    ): Promise<boolean> {
        const result = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
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

    async addPersonlessDistinctIdsBatch(
        entries: { teamId: number; distinctId: string }[]
    ): Promise<Map<string, boolean>> {
        if (entries.length === 0) {
            return new Map()
        }

        // Deduplicate entries to avoid PostgreSQL "ON CONFLICT DO UPDATE command cannot affect row a second time" error
        const seen = new Set<string>()
        const uniqueEntries: { teamId: number; distinctId: string }[] = []
        for (const entry of entries) {
            const key = `${entry.teamId}|${entry.distinctId}`
            if (!seen.has(key)) {
                seen.add(key)
                uniqueEntries.push(entry)
            }
        }

        const teamIds = uniqueEntries.map((e) => e.teamId)
        const distinctIds = uniqueEntries.map((e) => e.distinctId)

        const result = await this.postgres.query(
            PostgresUse.PERSONS_WRITE,
            `
                INSERT INTO posthog_personlessdistinctid (team_id, distinct_id, is_merged, created_at)
                SELECT team_id, distinct_id, false, now()
                FROM UNNEST($1::integer[], $2::text[]) AS batch(team_id, distinct_id)
                ON CONFLICT (team_id, distinct_id) DO UPDATE
                SET is_merged = posthog_personlessdistinctid.is_merged
                RETURNING team_id, distinct_id, is_merged
            `,
            [teamIds, distinctIds],
            'addPersonlessDistinctIdsBatch'
        )

        const resultMap = new Map<string, boolean>()
        for (const row of result.rows) {
            resultMap.set(`${row.team_id}|${row.distinct_id}`, row.is_merged)
        }
        return resultMap
    }

    async personPropertiesSize(personId: string, teamId: number): Promise<number> {
        const queryString = `
            SELECT COALESCE(pg_column_size(properties)::bigint, 0::bigint) AS total_props_bytes
            FROM posthog_person
            WHERE id = $1 AND team_id = $2`

        const { rows } = await this.postgres.query<PersonPropertiesSize>(
            PostgresUse.PERSONS_READ,
            queryString,
            [personId, teamId],
            'personPropertiesSize'
        )

        // the returned value from the DB query can be NULL if the record doesn't exist
        if (rows.length > 0) {
            return Number(rows[0].total_props_bytes)
        }

        return 0
    }

    async updatePerson(
        person: InternalPerson,
        update: PersonUpdateFields,
        tag?: string,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        let versionString = 'COALESCE(version, 0)::numeric + 1'
        if (update.version) {
            versionString = update.version.toString()
            delete update['version']
        }

        const unparsedUpdate = unparsePersonPartial(update)
        const updateValues = Object.values(unparsedUpdate)

        // short circuit if there are no updates to be made
        if (updateValues.length === 0) {
            return [person, [], false]
        }

        const values = [...updateValues, person.id, person.team_id].map(sanitizeJsonbValue)

        // Measure JSON field sizes after sanitization (using already sanitized values)
        const updateKeys = Object.keys(unparsedUpdate)
        for (let i = 0; i < updateKeys.length; i++) {
            const key = updateKeys[i]
            if (key === 'properties' || key === 'properties_last_updated_at' || key === 'properties_last_operation') {
                const sanitizedValue = values[i] // Already sanitized in the map above
                if (typeof sanitizedValue === 'string') {
                    personJsonFieldSizeHistogram
                        .labels({ operation: 'updatePerson', field: key })
                        .observe(sanitizedValue.length)
                }
            }
        }

        const calculatePropertiesSize = this.options.calculatePropertiesSize

        /*
         * Temporarily have two different queries for updatePerson to evaluate the impact of calculating
         * the size of the properties field during an update. If this is successful, we'll add a constraint check to the table
         * but we can't add that constraint check until we know the impact of adding that constraint check for every update/insert on Persons.
         * Added benefit, we can get more observability into the sizes of properties field, if we can turn this up to 100%
         */
        const idParamIndex = Object.values(update).length + 1
        const teamIdParamIndex = Object.values(update).length + 2
        const queryStringWithPropertiesSize = `UPDATE posthog_person SET version = ${versionString}, ${Object.keys(
            update
        ).map(
            (field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`
        )} WHERE id = $${idParamIndex} AND team_id = $${teamIdParamIndex}
        RETURNING *, COALESCE(pg_column_size(properties)::bigint, 0::bigint) as properties_size_bytes
        /* operation='updatePersonWithPropertiesSize',purpose='${tag || 'update'}' */`

        // Potentially overriding values badly if there was an update to the person after computing updateValues above
        const queryString = `UPDATE posthog_person SET version = ${versionString}, ${Object.keys(update).map(
            (field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`
        )} WHERE id = $${idParamIndex} AND team_id = $${teamIdParamIndex}
        RETURNING *
        /* operation='updatePerson',purpose='${tag || 'update'}' */`

        const shouldCalculatePropertiesSize =
            calculatePropertiesSize > 0 && Math.random() * 100 < calculatePropertiesSize

        const selectedQueryString = shouldCalculatePropertiesSize ? queryStringWithPropertiesSize : queryString

        try {
            const { rows } = await this.postgres.query<RawPerson & { properties_size_bytes?: string }>(
                tx ?? PostgresUse.PERSONS_WRITE,
                selectedQueryString,
                values,
                `updatePerson${tag ? `-${tag}` : ''}`
            )
            if (rows.length === 0) {
                throw new NoRowsUpdatedError(
                    `Person with id="${person.id}", team_id="${person.team_id}" and uuid="${person.uuid}" couldn't be updated`
                )
            }
            const updatedPerson = this.toPerson(rows[0])

            // Record properties size metric if we used the properties size query
            if (shouldCalculatePropertiesSize && rows[0].properties_size_bytes) {
                const propertiesSizeBytes = Number(rows[0].properties_size_bytes)
                personPropertiesSizeHistogram.labels({ at: 'updatePerson' }).observe(propertiesSizeBytes)
            }

            // Track the disparity between the version on the database and the version of the person we have in memory
            // Without races, the returned person (updatedPerson) should have a version that's only +1 the person in memory
            const versionDisparity = updatedPerson.version - person.version - 1
            if (versionDisparity > 0) {
                logger.info('🧑‍🦰', 'Person update version mismatch', {
                    team_id: updatedPerson.team_id,
                    person_id: updatedPerson.id,
                    version_disparity: versionDisparity,
                })
                personUpdateVersionMismatchCounter.inc()
            }

            const kafkaMessage = generateKafkaPersonUpdateMessage(updatedPerson)

            logger.debug(
                '🧑‍🦰',
                `Updated person ${updatedPerson.uuid} of team ${updatedPerson.team_id} to version ${updatedPerson.version}.`
            )

            return [updatedPerson, [kafkaMessage], versionDisparity > 0]
        } catch (error) {
            if (this.isPropertiesSizeConstraintViolation(error) && tag !== 'oversized_properties_remediation') {
                return await this.handleOversizedPersonProperties(person, update, tx)
            }

            // Re-throw other errors
            throw error
        }
    }

    async updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]> {
        try {
            const { rows } = await this.postgres.query<RawPerson>(
                PostgresUse.PERSONS_WRITE,
                `
                UPDATE posthog_person SET
                    properties = $1,
                    properties_last_updated_at = $2,
                    properties_last_operation = $3,
                    is_identified = $4,
                    version = COALESCE(version, 0)::numeric + 1
                WHERE team_id = $5 AND uuid = $6 AND version = $7
                RETURNING *
                `,
                [
                    JSON.stringify(personUpdate.properties),
                    JSON.stringify(personUpdate.properties_last_updated_at),
                    JSON.stringify(personUpdate.properties_last_operation),
                    personUpdate.is_identified,
                    personUpdate.team_id,
                    personUpdate.uuid,
                    personUpdate.version,
                ],
                'updatePersonAssertVersion'
            )

            if (rows.length === 0) {
                return [undefined, []]
            }

            const updatedPerson = this.toPerson(rows[0])

            const kafkaMessage = generateKafkaPersonUpdateMessage(updatedPerson)

            return [updatedPerson.version, [kafkaMessage]]
        } catch (error) {
            // Handle properties size constraint violation
            if (this.isPropertiesSizeConstraintViolation(error)) {
                // For updatePersonAssertVersion, we just log and reject like createPerson
                personPropertiesSizeViolationCounter.inc({
                    violation_type: 'update_person_assert_version_size_violation',
                })

                logger.warn('Rejecting person properties create/update, exceeds size limit', {
                    team_id: personUpdate.team_id,
                    person_id: personUpdate.id,
                    violation_type: 'update_person_assert_version_size_violation',
                })

                throw new PersonPropertiesSizeViolationError(
                    `Person properties update would exceed size limit`,
                    personUpdate.team_id,
                    personUpdate.id
                )
            }

            // Re-throw other errors
            throw error
        }
    }

    /**
     * Batch update multiple persons in a single query using UNNEST.
     * This uses a fixed query structure regardless of batch size, enabling prepared statement reuse.
     *
     * The method updates all mutable fields (properties, is_identified, created_at) and increments version.
     * It does NOT assert version - it always overwrites with the provided values.
     */
    async updatePersonsBatch(
        personUpdates: PersonUpdate[]
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: TopicMessage; error?: Error }>> {
        const results = new Map<
            string,
            { success: boolean; version?: number; kafkaMessage?: TopicMessage; error?: Error }
        >()

        if (personUpdates.length === 0) {
            return results
        }

        // Prepare arrays for UNNEST - one array per column we're updating/filtering on
        const uuids: string[] = []
        const teamIds: number[] = []
        const properties: string[] = []
        const propertiesLastUpdatedAt: string[] = []
        const propertiesLastOperation: string[] = []
        const isIdentified: boolean[] = []
        const createdAt: string[] = []

        for (const update of personUpdates) {
            uuids.push(update.uuid)
            teamIds.push(update.team_id)

            // Calculate final properties by applying set and unset operations
            const finalProperties = { ...update.properties }
            Object.entries(update.properties_to_set).forEach(([key, value]) => {
                finalProperties[key] = value
            })
            update.properties_to_unset.forEach((key) => {
                delete finalProperties[key]
            })

            // sanitizeJsonbValue already returns JSON.stringify(value) for objects, so don't double-stringify
            properties.push(sanitizeJsonbValue(finalProperties))
            propertiesLastUpdatedAt.push(sanitizeJsonbValue(update.properties_last_updated_at))
            propertiesLastOperation.push(sanitizeJsonbValue(update.properties_last_operation))
            isIdentified.push(update.is_identified)
            createdAt.push(update.created_at.toISO()!)
        }

        try {
            // Use UNNEST to pass arrays, keeping query structure constant for prepared statement reuse
            // Note: batch column names are prefixed with 'new_' to avoid any potential confusion with table columns
            const { rows } = await this.postgres.query<RawPerson>(
                PostgresUse.PERSONS_WRITE,
                `
                UPDATE posthog_person AS p SET
                    properties = batch.new_properties::jsonb,
                    properties_last_updated_at = batch.new_properties_last_updated_at::jsonb,
                    properties_last_operation = batch.new_properties_last_operation::jsonb,
                    is_identified = batch.new_is_identified,
                    created_at = batch.new_created_at::timestamp with time zone,
                    version = COALESCE(p.version, 0)::numeric + 1
                FROM UNNEST(
                    $1::uuid[],
                    $2::integer[],
                    $3::text[],
                    $4::text[],
                    $5::text[],
                    $6::boolean[],
                    $7::text[]
                ) AS batch(batch_uuid, batch_team_id, new_properties, new_properties_last_updated_at, new_properties_last_operation, new_is_identified, new_created_at)
                WHERE p.uuid = batch.batch_uuid AND p.team_id = batch.batch_team_id
                RETURNING p.*
                `,
                [uuids, teamIds, properties, propertiesLastUpdatedAt, propertiesLastOperation, isIdentified, createdAt],
                'updatePersonsBatch'
            )

            // Build a map of uuid -> updated person for quick lookup
            const updatedPersonsByUuid = new Map<string, InternalPerson>()
            for (const row of rows) {
                const person = this.toPerson(row)
                updatedPersonsByUuid.set(person.uuid, person)
            }

            // Process results for each input update
            for (const update of personUpdates) {
                const updatedPerson = updatedPersonsByUuid.get(update.uuid)
                if (updatedPerson) {
                    results.set(update.uuid, {
                        success: true,
                        version: updatedPerson.version,
                        kafkaMessage: generateKafkaPersonUpdateMessage(updatedPerson),
                    })
                } else {
                    // Person was not found/updated - likely deleted or merged
                    results.set(update.uuid, {
                        success: false,
                        error: new NoRowsUpdatedError(
                            `Person with uuid="${update.uuid}" and team_id="${update.team_id}" was not updated`
                        ),
                    })
                }
            }
        } catch (error) {
            // If the batch update fails due to properties size constraint, we need to handle it
            // For now, mark all as failed - the caller can fall back to individual updates
            if (this.isPropertiesSizeConstraintViolation(error)) {
                for (const update of personUpdates) {
                    results.set(update.uuid, {
                        success: false,
                        error: new PersonPropertiesSizeViolationError(
                            `Batch update failed due to properties size constraint`,
                            update.team_id,
                            update.id
                        ),
                    })
                }
            } else {
                // For other errors, mark all as failed with the original error
                for (const update of personUpdates) {
                    results.set(update.uuid, {
                        success: false,
                        error: error instanceof Error ? error : new Error(String(error)),
                    })
                }
            }
        }

        return results
    }

    async updateCohortsAndFeatureFlagsForMerge(
        teamID: Team['id'],
        sourcePersonID: InternalPerson['id'],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void> {
        // When personIDs change, update places depending on a person_id foreign key

        await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
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

    async inTransaction<T>(
        description: string,
        transaction: (tx: PersonRepositoryTransaction) => Promise<T>
    ): Promise<T> {
        return await this.inRawTransaction(description, async (tx: TransactionClient) => {
            const transactionClient = new PostgresPersonRepositoryTransaction(tx, this)
            return await transaction(transactionClient)
        })
    }

    async inRawTransaction<T>(description: string, transaction: (tx: TransactionClient) => Promise<T>): Promise<T> {
        return await this.postgres.transaction(PostgresUse.PERSONS_WRITE, description, transaction)
    }
}
