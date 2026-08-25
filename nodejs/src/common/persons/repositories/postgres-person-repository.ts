import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import { buildIntegerMatcher } from '~/common/config/config'
import { PERSON_DISTINCT_IDS_OUTPUT } from '~/common/outputs/persons'
import {
    oversizedPersonPropertiesTrimmedCounter,
    personCreateStrandedClaimCounter,
    personJsonFieldSizeHistogram,
    personPropertiesSizeViolationCounter,
} from '~/common/persons/metrics'
import { canTrimProperty } from '~/common/persons/person-property-utils'
import { PersonUpdate } from '~/common/persons/person-update-batch'
import { CreatePersonResult, MoveDistinctIdsResult, PersonPropertiesSize } from '~/common/utils/db/db'
import {
    moveDistinctIdsCountHistogram,
    personPropertiesSizeHistogram,
    personUpdateVersionMismatchCounter,
} from '~/common/utils/db/metrics'
import { PostgresRouter, PostgresUse, TransactionClient } from '~/common/utils/db/postgres'
import { generateKafkaPersonUpdateMessage, sanitizeJsonbValue, unparsePersonPartial } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'
import { NoRowsUpdatedError, sanitizeSqlIdentifier } from '~/common/utils/utils'
import { Properties } from '~/plugin-scaffold'
import {
    InternalPerson,
    PersonDistinctId,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    RawPerson,
    Team,
    TeamId,
    ValueMatcher,
} from '~/types'

import {
    DistinctIdConflictError,
    InternalPersonWithDistinctId,
    LifecycleMarkPerson,
    PersonClaimedByLifecycleOpError,
    PersonMessage,
    PersonPropertiesSizeViolationError,
    PersonRepository,
    PersonTombstoneBlockedError,
} from './person-repository'
import { PersonRepositoryTransaction } from './person-repository-transaction'
import { PostgresPersonRepositoryTransaction } from './postgres-person-repository-transaction'
import { RawPostgresPersonRepository } from './raw-postgres-person-repository'

const DEFAULT_PERSON_PROPERTIES_TRIM_TARGET_BYTES = 512 * 1024
const DEFAULT_PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES = 655360

// Person write paths return these explicit columns instead of *: the persons
// schema carries personhog-only columns (is_deleted) that must not leak into
// ingestion's InternalPerson objects.
const PERSON_COLUMN_NAMES = [
    'id',
    'uuid',
    'created_at',
    'team_id',
    'properties',
    'properties_last_updated_at',
    'properties_last_operation',
    'is_user_id',
    'version',
    'is_identified',
    'last_seen_at',
]
export const PERSON_COLUMNS = PERSON_COLUMN_NAMES.join(', ')
const PERSON_COLUMNS_PREFIXED = PERSON_COLUMN_NAMES.map((column) => `p.${column}`).join(', ')

// Postgres reports the violated index per partition (posthog_person_p58_team_id_uuid_idx),
// so match on the column instead of a fixed name. The distinct-ID constraint is named
// "unique distinct_id for team new", which this does not match.
function isUuidConstraintViolation(error: unknown): boolean {
    const constraint = (error as { constraint?: unknown } | null)?.constraint
    return typeof constraint === 'string' && constraint.includes('uuid')
}

function queryTag(base: string, callerTag?: string): string {
    return callerTag ? `${base}:${callerTag}` : base
}

export interface PostgresPersonRepositoryOptions {
    calculatePropertiesSize: number
    /** Limit used when comparing pg_column_size(properties) to decide whether to remediate */
    personPropertiesDbConstraintLimitBytes: number
    /** Target JSON size (stringified) to trim down to when remediating oversized properties */
    personPropertiesTrimTargetBytes: number
    /** Teams whose merge deletes tombstone the person row instead of hard-deleting it ('*' for all) */
    personMergeTombstoneTeamAllowlist: string
    /**
     * Teams whose person creation claims an existing unreachable row holding the same
     * (team_id, uuid) instead of inserting a duplicate. Person UUIDs are deterministic
     * (uuidv5 of team_id:distinct_id), so on teams where posthog_persondistinctid rows
     * were destroyed outside the write path, a returning user's create would otherwise
     * mint a second row with an identical (team_id, uuid). Scoped to affected teams
     * because the claim probe adds an index lookup to the hottest write path.
     * NOT the tombstone allowlist: that one routes to a query whose ON CONFLICT
     * (team_id, uuid) arbiter requires a unique index production does not have yet.
     */
    personCreateClaimTeamAllowlist: string
}

const DEFAULT_OPTIONS: PostgresPersonRepositoryOptions = {
    calculatePropertiesSize: 0,
    personPropertiesDbConstraintLimitBytes: DEFAULT_PERSON_PROPERTIES_DB_CONSTRAINT_LIMIT_BYTES,
    personPropertiesTrimTargetBytes: DEFAULT_PERSON_PROPERTIES_TRIM_TARGET_BYTES,
    personMergeTombstoneTeamAllowlist: '',
    personCreateClaimTeamAllowlist: '',
}

export class PostgresPersonRepository
    implements PersonRepository, RawPostgresPersonRepository, PersonRepositoryTransaction
{
    private options: PostgresPersonRepositoryOptions
    private isTombstoneTeam: ValueMatcher<number>
    private isClaimTeam: ValueMatcher<number>

    constructor(
        private postgres: PostgresRouter,
        options?: Partial<PostgresPersonRepositoryOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        this.isTombstoneTeam = buildIntegerMatcher(this.options.personMergeTombstoneTeamAllowlist, true)
        this.isClaimTeam = buildIntegerMatcher(this.options.personCreateClaimTeamAllowlist, true)
    }

    private async handleOversizedPersonProperties(
        person: InternalPerson,
        update: PersonUpdateFields,
        tx?: TransactionClient
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        const currentSize = await this.personPropertiesSize(person.id, person.team_id)

        if (currentSize >= this.options.personPropertiesDbConstraintLimitBytes) {
            try {
                personPropertiesSizeViolationCounter.inc({
                    violation_type: 'existing_record_violates_limit',
                })
                return await this.handleExistingOversizedRecord(person, update, tx)
            } catch {
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
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
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
            last_seen_at: row.last_seen_at ? DateTime.fromISO(row.last_seen_at).toUTC() : null,
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
        options: { forUpdate?: boolean; useReadReplica?: boolean; callerTag?: string } = {}
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
                posthog_person.is_identified,
                posthog_person.last_seen_at
            FROM posthog_person
            JOIN posthog_persondistinctid ON (
                posthog_persondistinctid.person_id = posthog_person.id
                AND posthog_persondistinctid.team_id = posthog_person.team_id
            )
            WHERE
                posthog_person.team_id = $1
                AND posthog_persondistinctid.team_id = $1
                AND posthog_persondistinctid.distinct_id = $2
                AND posthog_persondistinctid.is_deleted = false
                AND posthog_person.is_deleted = false`
        if (options.forUpdate) {
            // Locks the teamId and distinctId tied to this personId + this person's info
            queryString = queryString.concat(` FOR UPDATE`)
        }
        const values = [teamId, distinctId]

        const { rows } = await this.postgres.query<RawPerson>(
            options.useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
            queryString,
            values,
            queryTag('fetchPerson', options.callerTag)
        )

        if (rows.length > 0) {
            return this.toPerson(rows[0])
        }
    }

    /**
     * The person that already holds this (team_id, uuid).
     *
     * Read straight after a create loses the key, so the caller can resolve to that person
     * instead of failing. Recovering by distinct ID cannot find this row whenever the holder
     * does not own the distinct ID we were creating for, which is the case that turns a
     * conflict into a stuck consumer.
     *
     * Pass `tx` only from a path whose transaction is still usable. After a unique violation it
     * is not: Postgres aborts the transaction and rejects every later statement on it with
     * 25P02, and nothing here opens a savepoint (`postgres.ts` runs plain BEGIN/COMMIT/ROLLBACK).
     * A caller recovering from that error must omit `tx` and read on a pool connection, the way
     * the distinct-ID recovery in person-create-service already does. The holder was committed
     * by another transaction, which is why we conflicted with it, so a pool connection sees it.
     */
    private async fetchPersonByUuid(
        teamId: number,
        uuid: string,
        tx?: TransactionClient
    ): Promise<InternalPerson | undefined> {
        const { rows } = await this.postgres.query<RawPerson>(
            tx ?? PostgresUse.PERSONS_WRITE,
            `SELECT ${PERSON_COLUMNS} FROM posthog_person
             WHERE team_id = $1 AND uuid = $2 AND is_deleted = false`,
            [teamId, uuid],
            'fetchPersonByUuid'
        )
        return rows.length > 0 ? this.toPerson(rows[0]) : undefined
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        useReadReplica: boolean = true,
        callerTag?: string
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
                posthog_person.last_seen_at,
                posthog_persondistinctid.distinct_id
            FROM posthog_person
            JOIN posthog_persondistinctid ON (
                posthog_persondistinctid.person_id = posthog_person.id
                AND posthog_persondistinctid.team_id = posthog_person.team_id
            )
            JOIN UNNEST($1::integer[], $2::text[]) AS batch(team_id, distinct_id)
                ON posthog_persondistinctid.team_id = batch.team_id
                AND posthog_persondistinctid.distinct_id = batch.distinct_id
            WHERE
                posthog_persondistinctid.is_deleted = false
                AND posthog_person.is_deleted = false`

        const { rows } = await this.postgres.query<RawPerson & { distinct_id: string }>(
            useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
            queryString,
            [teamIds, distinctIds],
            queryTag('fetchPersonsByDistinctIds', callerTag)
        )

        return rows.map((row) => ({
            ...this.toPerson(row),
            distinct_id: row.distinct_id,
        }))
    }

    async fetchPersonsForUpdateByDistinctIds(
        teamId: number,
        distinctIds: string[],
        callerTag?: string
    ): Promise<InternalPersonWithDistinctId[]> {
        if (distinctIds.length === 0) {
            return []
        }

        const uniqueDistinctIds = [...new Set(distinctIds)]

        // ORDER BY person id gives concurrent multi-row lockers a deterministic
        // lock order, minimizing deadlocks between folded merges on overlapping
        // persons.
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
                posthog_person.last_seen_at,
                posthog_persondistinctid.distinct_id
            FROM posthog_person
            JOIN posthog_persondistinctid ON (
                posthog_persondistinctid.person_id = posthog_person.id
                AND posthog_persondistinctid.team_id = posthog_person.team_id
            )
            WHERE
                posthog_person.team_id = $1
                AND posthog_persondistinctid.team_id = $1
                AND posthog_persondistinctid.distinct_id = ANY($2::text[])
                AND posthog_persondistinctid.is_deleted = false
                AND posthog_person.is_deleted = false
            ORDER BY posthog_person.id
            FOR UPDATE`

        const { rows } = await this.postgres.query<RawPerson & { distinct_id: string }>(
            PostgresUse.PERSONS_WRITE,
            queryString,
            [teamId, uniqueDistinctIds],
            queryTag('fetchPersonsForUpdateByDistinctIds', callerTag)
        )

        return rows.map((row) => ({
            ...this.toPerson(row),
            distinct_id: row.distinct_id,
        }))
    }

    async fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        useReadReplica: boolean = true,
        callerTag?: string
    ): Promise<InternalPerson[]> {
        if (teamPersons.length === 0) {
            return []
        }

        // Deduplicate inputs to avoid duplicate rows in results
        const seen = new Set<string>()
        const uniqueTeamPersons = teamPersons.filter((p) => {
            const key = `${p.teamId}:${p.personId}`
            if (seen.has(key)) {
                return false
            }
            seen.add(key)
            return true
        })

        // Use UNNEST with paired arrays so each (teamId, personId) is matched as a tuple.
        // This prevents cross-team leakage where a person ID from one team could match
        // a row belonging to a different team in the batch.
        const teamIds = uniqueTeamPersons.map((p) => p.teamId)
        const personIds = uniqueTeamPersons.map((p) => p.personId)

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
                posthog_person.last_seen_at
            FROM posthog_person
            WHERE (posthog_person.team_id, posthog_person.uuid) IN (SELECT * FROM UNNEST($1::integer[], $2::uuid[]))
                AND posthog_person.is_deleted = false`

        const { rows } = await this.postgres.query<RawPerson>(
            useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
            queryString,
            [teamIds, personIds],
            queryTag('fetchPersonsByPersonIds', callerTag)
        )

        return rows.map(this.toPerson)
    }

    async fetchDistinctIdsForPersons(
        teamId: TeamId,
        personIntIds: string[],
        options?: { limitPerPerson?: number; useReadReplica?: boolean }
    ): Promise<Record<string, string[]>> {
        if (personIntIds.length === 0) {
            return {}
        }

        const useReadReplica = options?.useReadReplica ?? true
        // LATERAL JOIN applies the LIMIT per person_id, so a person with 100 distinct_ids
        // and limitPerPerson=1 reads one row from the index instead of 100.
        // When unlimited, we pass a very large LIMIT — postgres still uses the index seek per person.
        const perPersonLimit = options?.limitPerPerson != null ? options.limitPerPerson : Number.MAX_SAFE_INTEGER

        const queryString = `SELECT p.id AS person_id, pdi.distinct_id
            FROM unnest($2::bigint[]) AS p(id)
            JOIN LATERAL (
                SELECT distinct_id, id AS pdi_id
                FROM posthog_persondistinctid
                WHERE team_id = $1 AND person_id = p.id AND is_deleted = false
                ORDER BY id ASC
                LIMIT $3::bigint
            ) pdi ON true`

        const { rows } = await this.postgres.query<{ person_id: string; distinct_id: string }>(
            useReadReplica ? PostgresUse.PERSONS_READ : PostgresUse.PERSONS_WRITE,
            queryString,
            [teamId, personIntIds, perPersonLimit],
            'fetchDistinctIdsForPersons'
        )

        const result: Record<string, string[]> = {}
        for (const row of rows) {
            const key = String(row.person_id)
            const existing = result[key]
            if (existing) {
                existing.push(row.distinct_id)
            } else {
                result[key] = [row.distinct_id]
            }
        }
        return result
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
        // Teams outside the tombstone rollout run the query shipped on master,
        // untouched: clearing the allowlist is a full rollback to it.
        if (!this.isTombstoneTeam(teamId)) {
            if (this.isClaimTeam(teamId)) {
                return await this.createPersonWithStrandedClaim(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    primaryDistinctId,
                    extraDistinctIds,
                    tx
                )
            }
            return await this.createPersonLegacy(
                createdAt,
                properties,
                propertiesLastUpdatedAt,
                propertiesLastOperation,
                teamId,
                isUserId,
                isIdentified,
                uuid,
                primaryDistinctId,
                extraDistinctIds,
                tx
            )
        }

        // A conflicted create is undone by a compensating statement, which is only
        // atomic with the create inside a transaction. Without one, the created person
        // would be briefly visible to concurrent requests before the undo tombstones it.
        if (!tx) {
            return await this.inRawTransaction('createPerson', (newTx) =>
                this.createPerson(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    primaryDistinctId,
                    extraDistinctIds,
                    newTx
                )
            )
        }

        // Dedupe by distinct id: ON CONFLICT DO UPDATE raises 21000 when one command
        // carries the same key twice, even when the WHERE qual would exclude the row.
        const distinctIds = [primaryDistinctId, ...extraDistinctIds].filter(
            (entry, index, all) => all.findIndex((other) => other.distinctId === entry.distinctId) === index
        )
        for (const distinctId of distinctIds) {
            distinctId.version ||= 0
        }

        // Fresh inserts start at version 0; a tombstone conflict revives at death_version + 1 instead.
        const personVersion = 0

        try {
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

            // For new persons, set last_seen_at to the hour-rounded createdAt
            const lastSeenAt = createdAt.startOf('hour')

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
                lastSeenAt.toISO(),
            ]

            // A conflict with a tombstoned row is a revival: continue the version
            // counter above the death version so the reborn key outranks its own
            // ClickHouse tombstone from its first write. Conflicts with live rows
            // fail the WHERE qual and surface as CreationConflict below. The
            // arbiter requires the unique (team_id, uuid) index, which is why this
            // query only runs for allowlisted teams: enabling a team is gated on
            // that index existing in the environment.
            const query = `
                WITH inserted_person AS (
                    INSERT INTO posthog_person (
                        created_at, properties, properties_last_updated_at, properties_last_operation,
                        team_id, is_user_id, is_identified, uuid, version, last_seen_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (team_id, uuid) DO UPDATE SET
                        is_deleted = false,
                        version = COALESCE(posthog_person.version, 0) + 1,
                        properties = EXCLUDED.properties,
                        properties_last_updated_at = EXCLUDED.properties_last_updated_at,
                        properties_last_operation = EXCLUDED.properties_last_operation,
                        created_at = EXCLUDED.created_at,
                        is_user_id = EXCLUDED.is_user_id,
                        is_identified = EXCLUDED.is_identified,
                        last_seen_at = EXCLUDED.last_seen_at
                    WHERE posthog_person.is_deleted = true
                    RETURNING ${PERSON_COLUMNS}
                ),
                inserted_distinct_ids AS (
                    -- NOTE: Keep this in sync with the posthog_persondistinctid INSERT in addDistinctId
                    INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                    SELECT d.distinct_id, ip.id, $5, d.version
                    FROM inserted_person ip
                    CROSS JOIN unnest($11::text[], $12::bigint[]) AS d(distinct_id, version)
                    ON CONFLICT (team_id, distinct_id) DO UPDATE SET
                        person_id = EXCLUDED.person_id,
                        version = COALESCE(posthog_persondistinctid.version, 0) + 1,
                        is_deleted = false
                    WHERE posthog_persondistinctid.is_deleted = true
                    RETURNING id, distinct_id, version
                )
                SELECT
                    ip.*,
                    (
                        SELECT COALESCE(jsonb_agg(jsonb_build_object('id', d.id::text, 'distinct_id', d.distinct_id, 'version', d.version)), '[]'::jsonb)
                        FROM inserted_distinct_ids d
                    ) AS distinct_id_rows
                FROM inserted_person ip;`

            const { rows } = await this.postgres.query<
                RawPerson & { distinct_id_rows: { id: string; distinct_id: string; version: number }[] }
            >(
                tx ?? PostgresUse.PERSONS_WRITE,
                query,
                [
                    ...personParams,
                    distinctIds.map(({ distinctId }) => distinctId),
                    distinctIds.map(({ version }) => version),
                ],
                'insertPerson',
                'warn'
            )

            if (rows.length === 0) {
                // A live row already owns this (team_id, uuid): a concurrent create or
                // an existing person. Same outcome as a unique violation.
                return {
                    success: false,
                    error: 'CreationConflict',
                    distinctIds: distinctIds.map((d) => d.distinctId),
                    conflictingPerson: await this.fetchPersonByUuid(teamId, uuid, tx),
                }
            }

            const { distinct_id_rows: distinctIdRows, ...personRow } = rows[0]
            const person = this.toPerson(personRow)

            if (distinctIdRows.length < distinctIds.length) {
                // A live mapping owns one of the distinct ids, so the create must not
                // stand: a person row without that mapping would be unreachable by it
                // and would block the key's future revival. Tombstoning what this
                // statement wrote (a monotonic version bump, correct for revived rows
                // too) restores the pre-insert state.
                await this.postgres.query(
                    tx ?? PostgresUse.PERSONS_WRITE,
                    `WITH undone_distinct_ids AS (
                        UPDATE posthog_persondistinctid
                        SET is_deleted = true, version = COALESCE(version, 0) + 1
                        WHERE team_id = $2 AND id = ANY($1::bigint[]) AND is_deleted = false
                    )
                    UPDATE posthog_person
                    SET is_deleted = true,
                        version = COALESCE(version, 0) + 1,
                        properties = '{}'::jsonb,
                        properties_last_updated_at = '{}'::jsonb,
                        properties_last_operation = '{}'::jsonb
                    WHERE team_id = $2 AND id = $3 AND is_deleted = false`,
                    [distinctIdRows.map((row) => row.id), teamId, person.id],
                    'undoInsertPerson'
                )
                // A distinct-ID collision, not a uuid one: the caller resolves this by
                // re-fetching on distinct ID, so there is no holder to look up.
                return {
                    success: false,
                    error: 'CreationConflict',
                    distinctIds: distinctIds.map((d) => d.distinctId),
                }
            }

            const kafkaMessages: PersonMessage[] = [generateKafkaPersonUpdateMessage(person)]

            for (const row of distinctIdRows) {
                kafkaMessages.push({
                    output: PERSON_DISTINCT_IDS_OUTPUT,
                    value: Buffer.from(
                        JSON.stringify({
                            person_id: person.uuid,
                            team_id: teamId,
                            distinct_id: row.distinct_id,
                            version: Number(row.version),
                            is_deleted: 0,
                        })
                    ),
                })
            }

            return {
                success: true,
                person,
                messages: kafkaMessages,
                created: true,
            }
        } catch (error) {
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

    /**
     * createPersonLegacy plus one behavior change: when a live posthog_person row already
     * holds this (team_id, uuid) and no live distinct-ID mapping points at it, that row is
     * unreachable by the product (persons resolve only via distinct_id -> posthog_persondistinctid
     * -> person_id), so it is claimed - reset from this event and given the new mapping -
     * instead of a second row being inserted with an identical (team_id, uuid).
     *
     * The uuid is deterministic (uuidv5 of `${teamId}:${primaryDistinctId}`), so a claimed row
     * was originally created for this same distinct ID; the claim reunites a person with its
     * own row. The mapping keeps version 0, exactly like a fresh insert: the ClickHouse
     * overrides view only consumes versions > 0, and events already stamped with this uuid
     * point at the right person either way.
     *
     * Concurrency safety does not depend on any posthog_person index: a concurrent creator
     * for the same uuid necessarily carries the same primary distinct ID, so its mapping
     * insert collides on the unique (team_id, distinct_id) index and rolls this whole
     * single statement back, surfacing as CreationConflict just like the legacy path.
     */
    private async createPersonWithStrandedClaim(
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

        // Fresh inserts start at version 0; a claim continues the claimed row's counter so
        // its ClickHouse row (same uuid) is overwritten rather than outranked.
        const personVersion = 0

        try {
            const sanitizedProperties = sanitizeJsonbValue(properties)
            const sanitizedPropertiesLastUpdatedAt = sanitizeJsonbValue(propertiesLastUpdatedAt)
            const sanitizedPropertiesLastOperation = sanitizeJsonbValue(propertiesLastOperation)

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

            // For new persons, set last_seen_at to the hour-rounded createdAt
            const lastSeenAt = createdAt.startOf('hour')

            // holders is one probe on the (team_id, uuid) index; the reachability check is one
            // probe per holder on the (team_id, person_id) index. Duplicate groups can hold
            // several unreachable rows, so claimable takes exactly one (the oldest, min id);
            // repair tooling resolves the rest. The claim resets properties from this event rather
            // than reviving the stranded row's - deliberate, matching the tombstone revival
            // path, so data a deletion may have targeted is not resurrected.
            // The mapping insert has no ON CONFLICT: a collision must abort the whole
            // statement, same as the legacy path.
            const query = `
                WITH holders AS (
                    SELECT p.id,
                           EXISTS (
                               SELECT 1 FROM posthog_persondistinctid d
                               WHERE d.team_id = $5 AND d.person_id = p.id AND d.is_deleted = false
                           ) AS reachable
                    FROM posthog_person p
                    WHERE p.team_id = $5 AND p.uuid = $8 AND p.is_deleted = false
                ),
                claimable AS (
                    -- The oldest unreachable holder is selected with a scalar min(), not
                    -- ORDER BY id LIMIT 1: the pkey is (team_id, id), so an ordered LIMIT
                    -- lets the planner satisfy the sort by walking the team's id range and
                    -- filtering, which on a large team scans millions of rows when the match
                    -- is rare or absent. Equality on a scalar subquery leaves only a pkey
                    -- point probe in the plan space.
                    -- is_deleted is re-verified here (not only in holders) because under READ
                    -- COMMITTED, FOR UPDATE follows a concurrent update to the row's new version
                    -- and rechecks only this WHERE; without it, a row tombstoned between snapshot
                    -- and lock would be claimed without clearing its is_deleted flag. A row
                    -- tombstoned mid-race empties this CTE, falling through to a fresh insert.
                    SELECT p.id FROM posthog_person p
                    WHERE p.team_id = $5
                      AND p.id = (SELECT min(h.id) FROM holders h WHERE NOT h.reachable)
                      AND p.is_deleted = false
                    FOR UPDATE
                ),
                claimed AS (
                    UPDATE posthog_person p SET
                        created_at = $1,
                        properties = $2,
                        properties_last_updated_at = $3,
                        properties_last_operation = $4,
                        is_user_id = $6,
                        is_identified = $7,
                        version = COALESCE(p.version, 0) + 1,
                        last_seen_at = $10
                    FROM claimable c
                    WHERE p.team_id = $5 AND p.id = c.id
                    RETURNING ${PERSON_COLUMNS_PREFIXED}
                ),
                inserted AS (
                    INSERT INTO posthog_person (
                        created_at, properties, properties_last_updated_at, properties_last_operation,
                        team_id, is_user_id, is_identified, uuid, version, last_seen_at
                    )
                    SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10
                    WHERE NOT EXISTS (SELECT 1 FROM claimable)
                    RETURNING ${PERSON_COLUMNS}
                ),
                person AS (
                    SELECT *, true AS was_claimed FROM claimed
                    UNION ALL
                    SELECT *, false AS was_claimed FROM inserted
                ),
                inserted_distinct_ids AS (
                    -- NOTE: Keep this in sync with the posthog_persondistinctid INSERT in addDistinctId
                    INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                    SELECT d.distinct_id, p.id, $5, d.version
                    FROM person p
                    CROSS JOIN unnest($11::text[], $12::bigint[]) AS d(distinct_id, version)
                    RETURNING id, distinct_id, version
                )
                SELECT
                    p.*,
                    (SELECT count(*)::int FROM holders h WHERE h.reachable) AS reachable_holder_count,
                    (
                        SELECT COALESCE(jsonb_agg(jsonb_build_object('id', d.id::text, 'distinct_id', d.distinct_id, 'version', d.version)), '[]'::jsonb)
                        FROM inserted_distinct_ids d
                    ) AS distinct_id_rows
                FROM person p;`

            const { rows } = await this.postgres.query<
                RawPerson & {
                    was_claimed: boolean
                    reachable_holder_count: number
                    distinct_id_rows: { id: string; distinct_id: string; version: number }[]
                }
            >(
                tx ?? PostgresUse.PERSONS_WRITE,
                query,
                [
                    createdAt.toISO(),
                    sanitizedProperties,
                    sanitizedPropertiesLastUpdatedAt,
                    sanitizedPropertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    personVersion,
                    lastSeenAt.toISO(),
                    distinctIds.map(({ distinctId }) => distinctId),
                    distinctIds.map(({ version }) => version),
                ],
                'insertPersonWithStrandedClaim',
                'warn'
            )

            const {
                was_claimed: wasClaimed,
                reachable_holder_count: reachableHolderCount,
                distinct_id_rows: distinctIdRows,
                ...personRow
            } = rows[0]
            const person = this.toPerson(personRow)

            if (wasClaimed) {
                personCreateStrandedClaimCounter.inc({ outcome: 'claimed' })
            } else if (reachableHolderCount > 0) {
                // A reachable person already holds this uuid via a different distinct ID, so
                // this insert created a duplicate (team_id, uuid) - the pre-existing behavior.
                // Loud on purpose: these rows block the unique index build.
                personCreateStrandedClaimCounter.inc({ outcome: 'inserted_duplicate' })
                logger.warn('Created person duplicates a reachable (team_id, uuid)', {
                    team_id: teamId,
                    person_uuid: uuid,
                    reachable_holder_count: reachableHolderCount,
                })
            } else {
                personCreateStrandedClaimCounter.inc({ outcome: 'inserted' })
            }

            const kafkaMessages: PersonMessage[] = [generateKafkaPersonUpdateMessage(person)]

            for (const row of distinctIdRows) {
                kafkaMessages.push({
                    output: PERSON_DISTINCT_IDS_OUTPUT,
                    value: Buffer.from(
                        JSON.stringify({
                            person_id: person.uuid,
                            team_id: teamId,
                            distinct_id: row.distinct_id,
                            version: Number(row.version),
                            is_deleted: 0,
                        })
                    ),
                })
            }

            return {
                success: true,
                person,
                messages: kafkaMessages,
                created: true,
            }
        } catch (error) {
            // Same conflict contract as the legacy path: a unique violation means a
            // concurrent creator won the mapping, and the caller re-fetches by distinct ID.
            if (error instanceof Error && error.message.includes('unique constraint')) {
                return {
                    success: false,
                    error: 'CreationConflict',
                    distinctIds: distinctIds.map((d) => d.distinctId),
                    // No tx: the violation just aborted it, so a read on it would raise 25P02
                    // instead of returning the holder, and the throw would escape this catch
                    // and fail the merge this recovery exists to keep alive.
                    conflictingPerson: isUuidConstraintViolation(error)
                        ? await this.fetchPersonByUuid(teamId, uuid)
                        : undefined,
                }
            }

            if (this.isPropertiesSizeConstraintViolation(error)) {
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

            throw error
        }
    }

    // Master's createPerson, kept byte-for-byte for teams outside the tombstone
    // rollout. Remove together with the allowlist once tombstone mode is the default.
    private async createPersonLegacy(
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
                'last_seen_at',
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

            // For new persons, set last_seen_at to the hour-rounded createdAt
            const lastSeenAt = createdAt.startOf('hour')

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
                lastSeenAt.toISO(),
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
                        RETURNING ${PERSON_COLUMNS}
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

            const kafkaMessages: PersonMessage[] = [generateKafkaPersonUpdateMessage(person)]

            for (const distinctId of distinctIds) {
                kafkaMessages.push({
                    output: PERSON_DISTINCT_IDS_OUTPUT,
                    value: Buffer.from(
                        JSON.stringify({
                            person_id: person.uuid,
                            team_id: teamId,
                            distinct_id: distinctId.distinctId,
                            version: distinctId.version,
                            is_deleted: 0,
                        })
                    ),
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
                    // No tx: the violation just aborted it, so a read on it would raise 25P02
                    // instead of returning the holder, and the throw would escape this catch
                    // and fail the merge this recovery exists to keep alive.
                    conflictingPerson: isUuidConstraintViolation(error)
                        ? await this.fetchPersonByUuid(teamId, uuid)
                        : undefined,
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

    async deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<PersonMessage[]> {
        if (this.isTombstoneTeam(person.team_id)) {
            return await this.tombstonePersons([person], tx)
        }

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
                logger.warn('🔒', 'Deadlock detected — rolling back for the caller to retry.', {
                    team_id: person.team_id,
                    person_id: person.id,
                })
            }
            throw error
        }

        let kafkaMessages: PersonMessage[] = []

        if (rows.length > 0) {
            const [row] = rows
            kafkaMessages = [
                // The +100 outranks any version bump that landed between our stale read and the
                // delete; keep in sync with delete_person in posthog/models/person/util.py.
                generateKafkaPersonUpdateMessage(person, true, Number(row.version || 0) + 100),
            ]
        }
        return kafkaMessages
    }

    /**
     * Tombstone-mode delete: the row stays in place as the key's version floor, with the
     * death version stamped atomically and the properties scrubbed.
     *
     * Runs under the merge's lifecycle marks, which exclude every concurrent identity
     * mutation of these persons. The live-mapping guard on the stamp is therefore an
     * invariant assertion rather than the primary defense: rows it finds mean an
     * identity-mutation path skipped the mark claim. PersonTombstoneBlockedError feeds
     * the same refresh-and-retry handling as the hard delete's FK violation.
     */
    private async tombstonePersons(persons: InternalPerson[], tx?: TransactionClient): Promise<PersonMessage[]> {
        const teamId = persons[0].team_id
        const personById = new Map(persons.map((person) => [person.id, person]))
        const personIds = [...personById.keys()].sort((a, b) => (BigInt(a) < BigInt(b) ? -1 : 1))

        try {
            const live = await this.postgres.query<{ id: string }>(
                tx ?? PostgresUse.PERSONS_WRITE,
                `SELECT id FROM posthog_person
                 WHERE team_id = $1 AND id = ANY($2::bigint[]) AND is_deleted = false
                 ORDER BY id`,
                [teamId, personIds],
                'tombstonePersonsPrecheck'
            )
            if (live.rows.length === 0) {
                // Already tombstoned or gone — same outcome as an empty DELETE.
                return []
            }
            const liveIds = live.rows.map((row) => row.id)

            const { rows } = await this.postgres.query<{ id: string; version: string }>(
                tx ?? PostgresUse.PERSONS_WRITE,
                `UPDATE posthog_person p
                 SET is_deleted = true,
                     version = COALESCE(version, 0) + 1,
                     properties = '{}'::jsonb,
                     properties_last_updated_at = '{}'::jsonb,
                     properties_last_operation = '{}'::jsonb
                 WHERE team_id = $1 AND id = ANY($2::bigint[]) AND is_deleted = false
                   AND NOT EXISTS (
                       SELECT 1 FROM posthog_persondistinctid d
                       WHERE d.team_id = $1 AND d.person_id = p.id AND d.is_deleted = false
                   )
                 RETURNING id, version`,
                [teamId, liveIds],
                'tombstonePersons'
            )

            if (rows.length < liveIds.length) {
                throw new PersonTombstoneBlockedError('Live distinct ids still point at the person', teamId)
            }

            return rows.flatMap((row) => {
                const person = personById.get(String(row.id))
                if (!person) {
                    return []
                }
                return [generateKafkaPersonUpdateMessage({ ...person, properties: {} }, true, Number(row.version || 0))]
            })
        } catch (error) {
            if (error.code === '40P01') {
                logger.warn('🔒', 'Deadlock detected — rolling back for the caller to retry.', {
                    team_id: teamId,
                    person_ids: personIds,
                })
            }
            throw error
        }
    }

    async deletePersons(persons: InternalPerson[], tx?: TransactionClient): Promise<PersonMessage[]> {
        if (persons.length === 0) {
            return []
        }

        // All persons in a folded merge belong to one team.
        const teamId = persons[0].team_id
        if (this.isTombstoneTeam(teamId)) {
            return await this.tombstonePersons(persons, tx)
        }

        const personById = new Map(persons.map((person) => [person.id, person]))
        // Postgres acquires the row locks in index scan order (btree scans sort
        // the id keys ascending), not in array-parameter order, so concurrent
        // folds deleting overlapping persons lock in a consistent order either
        // way; sorting here just keeps the parameter and logs deterministic.
        const personIds = [...personById.keys()].sort((a, b) => (BigInt(a) < BigInt(b) ? -1 : 1))

        let rows: { id: string; version: string }[] = []
        try {
            const result = await this.postgres.query<{ id: string; version: string }>(
                tx ?? PostgresUse.PERSONS_WRITE,
                'DELETE FROM posthog_person WHERE team_id = $1 AND id = ANY($2::bigint[]) RETURNING id, version',
                [teamId, personIds],
                'deletePersons'
            )
            rows = result.rows
        } catch (error) {
            if (error.code === '40P01') {
                logger.warn('🔒', 'Deadlock detected — rolling back for the caller to retry.', {
                    team_id: teamId,
                    person_ids: personIds,
                })
            }
            throw error
        }

        return rows.flatMap((row) => {
            const person = personById.get(String(row.id))
            if (!person) {
                return []
            }
            return [
                // The +100 outranks any version bump that landed between our stale read and the
                // delete; keep in sync with delete_person in posthog/models/person/util.py.
                generateKafkaPersonUpdateMessage(person, true, Number(row.version || 0) + 100),
            ]
        })
    }

    async claimLifecycleMarks(
        opId: string,
        teamId: number,
        persons: LifecycleMarkPerson[],
        tx?: TransactionClient
    ): Promise<void> {
        // Sorted claims keep the mark-index insert order deterministic across concurrent
        // merges touching overlapping persons, so they block instead of deadlocking.
        const sorted = [...persons].sort((a, b) => (BigInt(a.personId) < BigInt(b.personId) ? -1 : 1))
        try {
            await this.postgres.query(
                tx ?? PostgresUse.PERSONS_WRITE,
                `INSERT INTO lifecycle_op (op_id, op_type, team_id, step, request, completed_at)
                 VALUES ($1, 'merge', $2, 'completed', $3::jsonb, now())`,
                [opId, teamId, JSON.stringify({ source: 'ingestion-merge' })],
                'claimLifecycleOp'
            )
            await this.postgres.query(
                tx ?? PostgresUse.PERSONS_WRITE,
                `INSERT INTO lifecycle_op_person (op_id, team_id, person_id, person_uuid, role, ordinal, status)
                 SELECT $1, $2, u.person_id, u.person_uuid, u.role, u.ordinal, 'marked'
                 FROM unnest($3::bigint[], $4::uuid[], $5::text[], $6::int[]) AS u(person_id, person_uuid, role, ordinal)`,
                [
                    opId,
                    teamId,
                    sorted.map((p) => p.personId),
                    sorted.map((p) => p.personUuid),
                    sorted.map((p) => p.role),
                    sorted.map((p) => p.ordinal ?? null),
                ],
                'claimLifecycleMarks'
            )
        } catch (error) {
            // The mark index turns "someone else holds this person" into a unique
            // violation; a duplicate op_id means a concurrent delivery of the same event.
            if (
                error.code === '23505' &&
                ['lifecycle_op_person_mark', 'lifecycle_op_pkey'].includes(error.constraint)
            ) {
                throw new PersonClaimedByLifecycleOpError(
                    'Person is claimed by a concurrent lifecycle operation',
                    teamId
                )
            }
            throw error
        }
    }

    async releaseLifecycleMarks(opId: string, teamId: number, tx?: TransactionClient): Promise<void> {
        // lifecycle_op_person rows go with the header via ON DELETE CASCADE. Running in
        // the claiming transaction means committed state never contains this merge's
        // marks: a concurrent claimant blocked on the index proceeds the moment we
        // commit, and the delete saga's sweeper never sees an ingestion op to resume.
        // The team and op-type guards keep a caller bug or op-id collision from ever
        // deleting another team's op or a delete saga's.
        await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            `DELETE FROM lifecycle_op WHERE op_id = $1 AND team_id = $2 AND op_type = 'merge'`,
            [opId, teamId],
            'releaseLifecycleMarks'
        )
    }

    async isPersonLive(person: InternalPerson, tx?: TransactionClient): Promise<boolean> {
        // Run this as its own statement after claimLifecycleMarks: a claim that waited
        // on the mark index resumes with its original snapshot, so only a fresh
        // statement reliably sees a tombstone committed during the wait. Under the mark
        // the answer is then stable until commit.
        const { rows } = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            'SELECT 1 FROM posthog_person WHERE team_id = $1 AND id = $2 AND is_deleted = false',
            [person.team_id, person.id],
            'isPersonLive'
        )
        return rows.length > 0
    }

    async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<PersonMessage[]> {
        // Teams outside the tombstone rollout run the query shipped on master,
        // untouched: clearing the allowlist is a full rollback to it.
        if (!this.isTombstoneTeam(person.team_id)) {
            return await this.addDistinctIdLegacy(person, distinctId, version, tx)
        }

        const insertResult = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            // NOTE: Keep this in sync with the posthog_persondistinctid INSERT in `createPerson`.
            // A conflict with a tombstoned mapping is a revival: repoint it and continue the
            // version counter above the death version. A live mapping is left untouched and
            // reported as a conflict, matching the pre-tombstone unique violation.
            `INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (team_id, distinct_id) DO UPDATE SET
                 person_id = EXCLUDED.person_id,
                 version = COALESCE(posthog_persondistinctid.version, 0) + 1,
                 is_deleted = false
             WHERE posthog_persondistinctid.is_deleted = true
             RETURNING *`,
            [distinctId, person.id, person.team_id, version],
            'addDistinctId',
            'warn'
        )

        if (insertResult.rows.length === 0) {
            throw new DistinctIdConflictError(
                'Distinct id is already owned by a live mapping',
                person.team_id,
                distinctId
            )
        }

        const {
            id,
            is_deleted,
            version: insertedVersion,
            ...personDistinctIdCreated
        } = insertResult.rows[0] as PersonDistinctId & { is_deleted: boolean }
        return [
            {
                output: PERSON_DISTINCT_IDS_OUTPUT,
                value: Buffer.from(
                    JSON.stringify({
                        ...personDistinctIdCreated,
                        version: Number(insertedVersion || 0),
                        person_id: person.uuid,
                        is_deleted: 0,
                    })
                ),
            },
        ]
    }

    // Master's addDistinctId, kept byte-for-byte for teams outside the tombstone
    // rollout. Remove together with the allowlist once tombstone mode is the default.
    private async addDistinctIdLegacy(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<PersonMessage[]> {
        const insertResult = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            // NOTE: Keep this in sync with the posthog_persondistinctid INSERT in `createPerson`
            'INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version) VALUES ($1, $2, $3, $4) RETURNING *',
            [distinctId, person.id, person.team_id, version],
            'addDistinctId',
            'warn'
        )

        const { id, ...personDistinctIdCreated } = insertResult.rows[0] as PersonDistinctId
        return [
            {
                output: PERSON_DISTINCT_IDS_OUTPUT,
                value: Buffer.from(
                    JSON.stringify({
                        ...personDistinctIdCreated,
                        version,
                        person_id: person.uuid,
                        is_deleted: 0,
                    })
                ),
            },
        ]
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
                          AND is_deleted = false
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
                      AND is_deleted = false
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
                output: PERSON_DISTINCT_IDS_OUTPUT,
                value: Buffer.from(
                    JSON.stringify({ ...usefulColumns, version, person_id: target.uuid, is_deleted: 0 })
                ),
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

    async countDistinctIdsForPersons(
        teamId: number,
        personIds: string[],
        tx?: TransactionClient
    ): Promise<Map<string, number>> {
        if (personIds.length === 0) {
            return new Map()
        }
        const { rows } = await this.postgres.query<{ person_id: string; count: string }>(
            tx ?? PostgresUse.PERSONS_WRITE,
            `SELECT person_id, count(*) AS count
                FROM posthog_persondistinctid
                WHERE team_id = $1 AND person_id = ANY($2::bigint[]) AND is_deleted = false
                GROUP BY person_id`,
            [teamId, personIds],
            'countDistinctIdsForPersons'
        )
        return new Map(rows.map((row) => [String(row.person_id), Number(row.count)]))
    }

    async moveDistinctIdsFromPersons(
        sources: InternalPerson[],
        target: InternalPerson,
        tx?: TransactionClient
    ): Promise<MoveDistinctIdsResult> {
        if (sources.length === 0) {
            return { success: true, messages: [], distinctIdsMoved: [] }
        }

        // Sorted ids keep the row-lock acquisition order deterministic across
        // concurrent folded merges touching overlapping source persons.
        const sourceIds = sources.map((source) => source.id).sort((a, b) => (BigInt(a) < BigInt(b) ? -1 : 1))

        let movedDistinctIdResult: QueryResult<any> | null = null
        try {
            movedDistinctIdResult = await this.postgres.query(
                tx ?? PostgresUse.PERSONS_WRITE,
                `UPDATE posthog_persondistinctid
                    SET person_id = $1, version = COALESCE(version, 0)::numeric + 1
                    WHERE person_id = ANY($2::bigint[])
                      AND team_id = $3
                      AND is_deleted = false
                    RETURNING *`,
                [target.id, sourceIds, target.team_id],
                'updateDistinctIdPersonFold'
            )
        } catch (error) {
            if (
                (error as Error).message.includes(
                    'insert or update on table "posthog_persondistinctid" violates foreign key constraint'
                )
            ) {
                // Same race as moveDistinctIds: the target person was deleted
                // between fetch and update; the caller retries with fresh data.
                logger.warn('😵', 'Target person no longer exists', {
                    team_id: target.team_id,
                    person_id: target.id,
                })
                moveDistinctIdsCountHistogram.observe(0)
                return {
                    success: false,
                    error: 'TargetNotFound',
                }
            }

            throw error
        }

        // Unlike the single-source variant, zero moved rows for a source is not
        // a failure here: a concurrently completed merge may have already moved
        // it, which the folded merge treats as satisfied.
        const kafkaMessages = []
        for (const row of movedDistinctIdResult.rows) {
            const { id, version: versionStr, ...usefulColumns } = row as PersonDistinctId
            const version = Number(versionStr || 0)
            kafkaMessages.push({
                output: PERSON_DISTINCT_IDS_OUTPUT,
                value: Buffer.from(
                    JSON.stringify({ ...usefulColumns, version, person_id: target.uuid, is_deleted: 0 })
                ),
            })
        }

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
                WHERE person_id = $1 AND team_id = $2 AND is_deleted = false
                ORDER BY id
                LIMIT $3
            `
            : `
                SELECT distinct_id
                FROM posthog_persondistinctid
                WHERE person_id = $1 AND team_id = $2 AND is_deleted = false
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
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
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
        )} WHERE id = $${idParamIndex} AND team_id = $${teamIdParamIndex} AND is_deleted = false
        RETURNING ${PERSON_COLUMNS}, COALESCE(pg_column_size(properties)::bigint, 0::bigint) as properties_size_bytes
        /* operation='updatePersonWithPropertiesSize',purpose='${tag || 'update'}' */`

        // Potentially overriding values badly if there was an update to the person after computing updateValues above
        const queryString = `UPDATE posthog_person SET version = ${versionString}, ${Object.keys(update).map(
            (field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`
        )} WHERE id = $${idParamIndex} AND team_id = $${teamIdParamIndex} AND is_deleted = false
        RETURNING ${PERSON_COLUMNS}
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

    async updatePersonAssertVersion(personUpdate: PersonUpdate): Promise<[number | undefined, PersonMessage[]]> {
        try {
            // Calculate final properties by applying set and unset operations
            const finalProperties = { ...personUpdate.properties }
            Object.entries(personUpdate.properties_to_set).forEach(([key, value]) => {
                finalProperties[key] = value
            })
            personUpdate.properties_to_unset.forEach((key) => {
                delete finalProperties[key]
            })

            const { rows } = await this.postgres.query<RawPerson>(
                PostgresUse.PERSONS_WRITE,
                `
                UPDATE posthog_person SET
                    properties = $1,
                    properties_last_updated_at = $2,
                    properties_last_operation = $3,
                    is_identified = $4,
                    last_seen_at = $5,
                    version = COALESCE(version, 0)::numeric + 1
                WHERE team_id = $6 AND uuid = $7 AND version = $8 AND is_deleted = false
                RETURNING ${PERSON_COLUMNS}
                `,
                [
                    JSON.stringify(finalProperties),
                    JSON.stringify(personUpdate.properties_last_updated_at),
                    JSON.stringify(personUpdate.properties_last_operation),
                    personUpdate.is_identified,
                    personUpdate.last_seen_at?.toISO() ?? null,
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
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: PersonMessage; error?: Error }>> {
        const results = new Map<
            string,
            { success: boolean; version?: number; kafkaMessage?: PersonMessage; error?: Error }
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
        const lastSeenAt: (string | null)[] = []

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
            lastSeenAt.push(update.last_seen_at?.toISO() ?? null)
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
                    last_seen_at = batch.new_last_seen_at::timestamp with time zone,
                    version = COALESCE(p.version, 0)::numeric + 1
                FROM UNNEST(
                    $1::uuid[],
                    $2::integer[],
                    $3::text[],
                    $4::text[],
                    $5::text[],
                    $6::boolean[],
                    $7::text[],
                    $8::text[]
                ) AS batch(batch_uuid, batch_team_id, new_properties, new_properties_last_updated_at, new_properties_last_operation, new_is_identified, new_created_at, new_last_seen_at)
                WHERE p.uuid = batch.batch_uuid AND p.team_id = batch.batch_team_id AND p.is_deleted = false
                RETURNING ${PERSON_COLUMNS_PREFIXED}
                `,
                [
                    uuids,
                    teamIds,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    isIdentified,
                    createdAt,
                    lastSeenAt,
                ],
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

    async updateCohortsAndFeatureFlagsForMergeBatch(
        teamID: Team['id'],
        sourcePersonIDs: InternalPerson['id'][],
        targetPersonID: InternalPerson['id'],
        tx?: TransactionClient
    ): Promise<void> {
        if (sourcePersonIDs.length === 0) {
            return
        }

        // Multi-source variant of updateCohortsAndFeatureFlagsForMerge — same
        // two operations, one round-trip for all folded source persons.
        await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
            `WITH cohort_update AS (
                UPDATE posthog_cohortpeople
                SET person_id = $1
                WHERE person_id = ANY($2::bigint[])
                RETURNING person_id
            ),
            deletions AS (
                DELETE FROM posthog_featureflaghashkeyoverride
                WHERE team_id = $3 AND person_id = ANY($2::bigint[])
                RETURNING team_id, person_id, feature_flag_key, hash_key
            )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, $1, feature_flag_key, hash_key
                FROM deletions
                ON CONFLICT DO NOTHING`,
            [targetPersonID, sourcePersonIDs, teamID],
            'updateCohortAndFeatureFlagsPeopleBatch'
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
