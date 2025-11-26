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
    /** Enable person table cutover migration */
    tableCutoverEnabled?: boolean
    /** New person table name for cutover migration */
    newTableName?: string
    /** Person ID offset threshold - person IDs >= this value route to new table */
    newTableIdOffset?: number
}

const DEFAULT_OPTIONS: PostgresPersonRepositoryOptions = {
    calculatePropertiesSize: 0,
    personPropertiesDbConstraintLimitBytes: DEFAULT_PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES,
    personPropertiesTrimTargetBytes: DEFAULT_PERSON_PROPERTIES_TRIM_TARGET_BYTES,
    tableCutoverEnabled: false,
    newTableName: 'posthog_person_new',
    newTableIdOffset: Number.MAX_SAFE_INTEGER,
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

    private getTableName(personId?: string, person?: InternalPerson): string {
        if (!this.options.tableCutoverEnabled || !this.options.newTableName || !this.options.newTableIdOffset) {
            return 'posthog_person'
        }

        // If person object provided with routing decision, use it
        if (person?.__useNewTable !== undefined) {
            return person.__useNewTable ? this.options.newTableName : 'posthog_person'
        }

        // Fall back to ID-based routing
        if (!personId) {
            return 'posthog_person'
        }

        const numericPersonId = parseInt(personId, 10)
        if (isNaN(numericPersonId)) {
            return 'posthog_person'
        }

        // Always return unsanitized name - callers must sanitize before SQL interpolation
        return numericPersonId >= this.options.newTableIdOffset ? this.options.newTableName : 'posthog_person'
    }

    private async handleOversizedPersonProperties(
        person: InternalPerson,
        update: PersonUpdateFields,
        tx?: TransactionClient
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        const currentSize = await this.personPropertiesSize(person.id, person.team_id, person)

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

        if (this.options.tableCutoverEnabled && this.options.newTableName && this.options.newTableIdOffset) {
            // First, get the person_id from posthog_persondistinctid
            const distinctIdQuery = `
                SELECT person_id
                FROM posthog_persondistinctid
                WHERE team_id = $1 AND distinct_id = $2
                LIMIT 1`

            const { rows: distinctIdRows } = await this.postgres.query<{ person_id: string }>(
                options.useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
                distinctIdQuery,
                [teamId, distinctId],
                'fetchPersonDistinctIdMapping'
            )

            if (distinctIdRows.length === 0) {
                return undefined
            }

            const personId = distinctIdRows[0].person_id
            const forUpdateClause = options.forUpdate ? ' FOR UPDATE' : ''

            // Check new table first (by existence, not by ID threshold)
            const newTableName = sanitizeSqlIdentifier(this.options.newTableName)
            const personQueryNew = `
                SELECT
                    id,
                    uuid,
                    created_at,
                    team_id,
                    properties,
                    properties_last_updated_at,
                    properties_last_operation,
                    is_user_id,
                    version,
                    is_identified
                FROM ${newTableName}
                WHERE team_id = $1 AND id = $2${forUpdateClause}`

            const { rows: newTableRows } = await this.postgres.query<RawPerson>(
                options.useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
                personQueryNew,
                [teamId, personId],
                'fetchPersonFromNewTable'
            )

            if (newTableRows.length > 0) {
                const person = this.toPerson(newTableRows[0])
                // Mark that this person exists in the new table
                ;(person as any).__useNewTable = true
                return person
            }

            // Fall back to old table
            const personQueryOld = `
                SELECT
                    id,
                    uuid,
                    created_at,
                    team_id,
                    properties,
                    properties_last_updated_at,
                    properties_last_operation,
                    is_user_id,
                    version,
                    is_identified
                FROM posthog_person
                WHERE team_id = $1 AND id = $2${forUpdateClause}`

            const { rows: oldTableRows } = await this.postgres.query<RawPerson>(
                options.useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
                personQueryOld,
                [teamId, personId],
                'fetchPersonFromOldTable'
            )

            if (oldTableRows.length > 0) {
                const person = this.toPerson(oldTableRows[0])

                // Opportunistically copy person to new table
                // This allows all future operations to go directly to new table (avoiding slow triggers)
                // Skip copy when using read replica to maintain read-only intent
                if (!options.useReadReplica) {
                    try {
                        const copyQuery = `
                            INSERT INTO ${newTableName} (
                                id,
                                uuid,
                                created_at,
                                team_id,
                                properties,
                                properties_last_updated_at,
                                properties_last_operation,
                                is_user_id,
                                version,
                                is_identified
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                            ON CONFLICT (team_id, id) DO NOTHING
                            RETURNING id`

                        await this.postgres.query(
                            PostgresUse.PERSONS_WRITE,
                            copyQuery,
                            [
                                person.id,
                                person.uuid,
                                person.created_at.toISO(),
                                person.team_id,
                                sanitizeJsonbValue(person.properties),
                                sanitizeJsonbValue(person.properties_last_updated_at),
                                sanitizeJsonbValue(person.properties_last_operation),
                                person.is_user_id,
                                person.version,
                                person.is_identified,
                            ],
                            'copyPersonToNewTable'
                        )

                        // Person is now in new table, future operations can use it
                        ;(person as any).__useNewTable = true
                    } catch (error) {
                        // If copy fails for any reason, log but continue with old table routing
                        logger.warn('Failed to copy person to new table', {
                            error: error instanceof Error ? error.message : String(error),
                            person_id: person.id,
                            team_id: person.team_id,
                        })
                        ;(person as any).__useNewTable = false
                    }
                } else {
                    // When using read replica, don't attempt write operation
                    ;(person as any).__useNewTable = false
                }

                return person
            }
        } else {
            const forUpdateClause = options.forUpdate ? ' FOR UPDATE' : ''
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
                    posthog_person.is_identified
                FROM posthog_person
                JOIN posthog_persondistinctid ON (posthog_persondistinctid.person_id = posthog_person.id)
                WHERE
                    posthog_person.team_id = $1
                    AND posthog_persondistinctid.team_id = $1
                    AND posthog_persondistinctid.distinct_id = $2${forUpdateClause}`

            const { rows } = await this.postgres.query<RawPerson>(
                options.useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
                queryString,
                [teamId, distinctId],
                'fetchPerson'
            )

            if (rows.length > 0) {
                return this.toPerson(rows[0])
            }
        }
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[]
    ): Promise<InternalPersonWithDistinctId[]> {
        if (teamPersons.length === 0) {
            return []
        }

        const params = teamPersons.flatMap((person) => [person.teamId, person.distinctId])

        if (this.options.tableCutoverEnabled && this.options.newTableName && this.options.newTableIdOffset) {
            // First, get all person_id mappings from posthog_persondistinctid
            const conditions = teamPersons
                .map((_, index) => {
                    const teamIdParam = index * 2 + 1
                    const distinctIdParam = index * 2 + 2
                    return `(team_id = $${teamIdParam} AND distinct_id = $${distinctIdParam})`
                })
                .join(' OR ')

            const distinctIdQuery = `
                SELECT person_id, distinct_id, team_id
                FROM posthog_persondistinctid
                WHERE ${conditions}`

            const { rows: distinctIdRows } = await this.postgres.query<{
                person_id: string
                distinct_id: string
                team_id: number
            }>(PostgresUse.PERSONS_READ, distinctIdQuery, params, 'fetchPersonDistinctIdMappings')

            if (distinctIdRows.length === 0) {
                return []
            }

            // Group person IDs by table using ID-based routing
            const oldTablePersonIds: string[] = []
            const newTablePersonIds: string[] = []
            const personIdToDistinctId = new Map<string, { distinct_id: string; team_id: number }>()

            for (const row of distinctIdRows) {
                const tableName = this.getTableName(row.person_id)
                if (tableName === 'posthog_person') {
                    oldTablePersonIds.push(row.person_id)
                } else {
                    newTablePersonIds.push(row.person_id)
                }
                personIdToDistinctId.set(row.person_id, {
                    distinct_id: row.distinct_id,
                    team_id: row.team_id,
                })
            }

            const allPersons: (RawPerson & { distinct_id: string })[] = []

            // Fetch from old table if needed
            if (oldTablePersonIds.length > 0) {
                // Build conditions matching both person_id and team_id to avoid full table scans
                const oldTableConditions = oldTablePersonIds
                    .map((_personId, index) => {
                        const idParam = index * 2 + 1
                        const teamIdParam = index * 2 + 2
                        return `(id = $${idParam} AND team_id = $${teamIdParam})`
                    })
                    .join(' OR ')

                const oldTableParams = oldTablePersonIds.flatMap((personId) => {
                    const mapping = personIdToDistinctId.get(personId)!
                    return [personId, mapping.team_id]
                })

                const oldTableQuery = `
                    SELECT
                        id,
                        uuid,
                        created_at,
                        team_id,
                        properties,
                        properties_last_updated_at,
                        properties_last_operation,
                        is_user_id,
                        version,
                        is_identified
                    FROM posthog_person
                    WHERE ${oldTableConditions}`

                const { rows: oldTableRows } = await this.postgres.query<RawPerson>(
                    PostgresUse.PERSONS_READ,
                    oldTableQuery,
                    oldTableParams,
                    'fetchPersonsFromOldTable'
                )

                for (const row of oldTableRows) {
                    const mapping = personIdToDistinctId.get(String(row.id))
                    if (mapping) {
                        allPersons.push({ ...row, distinct_id: mapping.distinct_id })
                    }
                }
            }

            // Fetch from new table if needed
            if (newTablePersonIds.length > 0) {
                // Build conditions matching both person_id and team_id to avoid full table scans
                const newTableConditions = newTablePersonIds
                    .map((_personId, index) => {
                        const idParam = index * 2 + 1
                        const teamIdParam = index * 2 + 2
                        return `(id = $${idParam} AND team_id = $${teamIdParam})`
                    })
                    .join(' OR ')

                const newTableParams = newTablePersonIds.flatMap((personId) => {
                    const mapping = personIdToDistinctId.get(personId)!
                    return [personId, mapping.team_id]
                })

                const safeNewTableName = sanitizeSqlIdentifier(this.options.newTableName)
                const newTableQuery = `
                    SELECT
                        id,
                        uuid,
                        created_at,
                        team_id,
                        properties,
                        properties_last_updated_at,
                        properties_last_operation,
                        is_user_id,
                        version,
                        is_identified
                    FROM ${safeNewTableName}
                    WHERE ${newTableConditions}`

                const { rows: newTableRows } = await this.postgres.query<RawPerson>(
                    PostgresUse.PERSONS_READ,
                    newTableQuery,
                    newTableParams,
                    'fetchPersonsFromNewTable'
                )

                for (const row of newTableRows) {
                    const mapping = personIdToDistinctId.get(String(row.id))
                    if (mapping) {
                        allPersons.push({ ...row, distinct_id: mapping.distinct_id })
                    }
                }
            }

            return allPersons.map((row) => ({
                ...this.toPerson(row),
                distinct_id: row.distinct_id,
            }))
        } else {
            const conditions = teamPersons
                .map((_, index) => {
                    const teamIdParam = index * 2 + 1
                    const distinctIdParam = index * 2 + 2
                    return `(posthog_persondistinctid.team_id = $${teamIdParam} AND posthog_persondistinctid.distinct_id = $${distinctIdParam} AND posthog_person.team_id = $${teamIdParam})`
                })
                .join(' OR ')

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
                JOIN posthog_persondistinctid ON (posthog_persondistinctid.person_id = posthog_person.id AND posthog_persondistinctid.team_id = posthog_person.team_id)
                WHERE ${conditions}`

            const { rows } = await this.postgres.query<RawPerson & { distinct_id: string }>(
                PostgresUse.PERSONS_READ,
                queryString,
                params,
                'fetchPersonsByDistinctIds'
            )

            return rows.map((row) => ({
                ...this.toPerson(row),
                distinct_id: row.distinct_id,
            }))
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
        tx?: TransactionClient,
        // Used to support dual-write; we want to force the id a person is created with to prevent drift
        forcedId?: number
    ): Promise<CreatePersonResult> {
        distinctIds = distinctIds || []

        for (const distinctId of distinctIds) {
            distinctId.version ||= 0
        }

        // The Person is being created, and so we can hardcode version 0!
        const personVersion = 0

        try {
            const baseColumns = [
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

            // When cutover is enabled and no forcedId, we need to explicitly call nextval() for id
            // because partitioned tables don't automatically apply DEFAULT values when the column is omitted
            const useDefaultId = !forcedId

            let columns: string[]
            let valuePlaceholders: string

            if (useDefaultId) {
                // Include 'id' in columns but use nextval() to explicitly get next sequence value
                // We need this for partitioned tables which don't properly inherit DEFAULT constraints
                columns = ['id', ...baseColumns]
                valuePlaceholders = `nextval('posthog_person_id_seq'), ${baseColumns.map((_, i) => `$${i + 1}`).join(', ')}`
            } else if (forcedId) {
                // Include 'id' in columns and use $1 for its value
                columns = ['id', ...baseColumns]
                valuePlaceholders = columns.map((_, i) => `$${i + 1}`).join(', ')
            } else {
                // Don't include 'id' - let the table's DEFAULT handle it
                columns = baseColumns
                valuePlaceholders = columns.map((_, i) => `$${i + 1}`).join(', ')
            }

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

            const baseParams = [
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
            const personParams = forcedId ? [forcedId, ...baseParams] : baseParams

            // Find the actual index of team_id in the personParams array (1-indexed for SQL)
            const teamIdParamIndex = personParams.indexOf(teamId) + 1
            // Use personParams.length instead of columns.length because when useDefaultId is true,
            // columns includes 'id' but personParams doesn't include an id value
            const distinctIdVersionStartIndex = personParams.length + 1
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

            const tableName =
                this.options.tableCutoverEnabled && this.options.newTableName && this.options.newTableIdOffset
                    ? sanitizeSqlIdentifier(this.options.newTableName)
                    : 'posthog_person'

            const query =
                `WITH inserted_person AS (
                        INSERT INTO ${tableName} (${columns.join(', ')})
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
            const tableName = sanitizeSqlIdentifier(this.getTableName(person.id, person))
            const result = await this.postgres.query<{ version: string }>(
                tx ?? PostgresUse.PERSONS_WRITE,
                `DELETE FROM ${tableName} WHERE team_id = $1 AND id = $2 RETURNING version`,
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
        const result = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
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
            tx ?? PostgresUse.PERSONS_WRITE,
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

    async personPropertiesSize(personId: string, teamId: number, person?: InternalPerson): Promise<number> {
        const tableName = sanitizeSqlIdentifier(this.getTableName(personId, person))

        // For partitioned tables, we need team_id for efficient querying
        const queryString = `
            SELECT COALESCE(pg_column_size(properties)::bigint, 0::bigint) AS total_props_bytes
            FROM ${tableName}
            WHERE team_id = $1 AND id = $2`

        const { rows } = await this.postgres.query<PersonPropertiesSize>(
            PostgresUse.PERSONS_READ,
            queryString,
            [teamId, personId],
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

        const values = [...updateValues].map(sanitizeJsonbValue)

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
        const tableName = sanitizeSqlIdentifier(this.getTableName(person.id, person))

        // Add team_id and person_id to values for WHERE clause (for partitioning)
        const allValues = [...values, person.team_id, person.id]

        /*
         * Temporarily have two different queries for updatePerson to evaluate the impact of calculating
         * the size of the properties field during an update. If this is successful, we'll add a constraint check to the table
         * but we can't add that constraint check until we know the impact of adding that constraint check for every update/insert on Persons.
         * Added benefit, we can get more observability into the sizes of properties field, if we can turn this up to 100%
         */
        const updateFieldsCount = Object.values(update).length
        const teamIdParamIndex = updateFieldsCount + 1
        const personIdParamIndex = updateFieldsCount + 2

        const queryStringWithPropertiesSize = `UPDATE ${tableName} SET version = ${versionString}, ${Object.keys(
            update
        ).map(
            (field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`
        )} WHERE team_id = $${teamIdParamIndex} AND id = $${personIdParamIndex}
        RETURNING *, COALESCE(pg_column_size(properties)::bigint, 0::bigint) as properties_size_bytes
        /* operation='updatePersonWithPropertiesSize',purpose='${tag || 'update'}' */`

        // Potentially overriding values badly if there was an update to the person after computing updateValues above
        const queryString = `UPDATE ${tableName} SET version = ${versionString}, ${Object.keys(update).map(
            (field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`
        )} WHERE team_id = $${teamIdParamIndex} AND id = $${personIdParamIndex}
        RETURNING *
        /* operation='updatePerson',purpose='${tag || 'update'}' */`

        const shouldCalculatePropertiesSize =
            calculatePropertiesSize > 0 && Math.random() * 100 < calculatePropertiesSize

        const selectedQueryString = shouldCalculatePropertiesSize ? queryStringWithPropertiesSize : queryString

        try {
            const { rows } = await this.postgres.query<RawPerson & { properties_size_bytes?: string }>(
                tx ?? PostgresUse.PERSONS_WRITE,
                selectedQueryString,
                allValues,
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
            const params = [
                JSON.stringify(personUpdate.properties),
                JSON.stringify(personUpdate.properties_last_updated_at),
                JSON.stringify(personUpdate.properties_last_operation),
                personUpdate.is_identified,
                personUpdate.team_id,
                personUpdate.uuid,
                personUpdate.version,
            ]

            const tableName = sanitizeSqlIdentifier(this.getTableName(personUpdate.id, personUpdate))
            const queryString = `
                UPDATE ${tableName} SET
                    properties = $1,
                    properties_last_updated_at = $2,
                    properties_last_operation = $3,
                    is_identified = $4,
                    version = COALESCE(version, 0)::numeric + 1
                WHERE team_id = $5 AND uuid = $6 AND version = $7
                RETURNING *`

            const { rows } = await this.postgres.query<RawPerson>(
                PostgresUse.PERSONS_WRITE,
                queryString,
                params,
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
