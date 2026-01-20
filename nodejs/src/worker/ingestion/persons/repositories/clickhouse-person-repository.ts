import { DateTime } from 'luxon'

import { Properties } from '@posthog/plugin-scaffold'

import { ClickHouseRouter } from '~/utils/db/clickhouse'

import { TopicMessage } from '../../../../kafka/producer'
import {
    InternalPerson,
    PersonPropertyFilter,
    PersonUpdateFields,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    Team,
    TeamId,
} from '../../../../types'
import { CreatePersonResult } from '../../../../utils/db/db'
import { parseJSON } from '../../../../utils/json-parse'
import { escapeClickHouseString } from '../../../../utils/utils'
import { PersonUpdate } from '../person-update-batch'
import { InternalPersonWithDistinctId, PersonRepository } from './person-repository'
import { PersonRepositoryTransaction } from './person-repository-transaction'

/**
 * Read-only ClickHouse implementation of PersonRepository.
 * This is useful for analytics, debugging, and read-only operations where you need
 * direct access to ClickHouse person data without going through Postgres.
 *
 * Note: This only implements read methods. Write operations are not supported and will
 * throw errors if called.
 */
export class ClickHousePersonRepository implements PersonRepository {
    constructor(private clickHouseRouter: ClickHouseRouter) {}

    fetchPerson(
        _teamId: Team['id'],
        _distinctId: string,
        _options?: { forUpdate?: boolean; useReadReplica?: boolean }
    ): Promise<InternalPerson | undefined> {
        throw new Error('fetchPerson operation not yet supported in ClickHousePersonRepository')
    }

    fetchPersonsByDistinctIds(
        _teamPersons: { teamId: TeamId; distinctId: string }[],
        _useReadReplica?: boolean
    ): Promise<InternalPersonWithDistinctId[]> {
        throw new Error('fetchPersonsByDistinctIds operation not yet supported in ClickHousePersonRepository')
    }

    async countPersonsByProperties(teamPersons: {
        teamId: TeamId
        properties: PersonPropertyFilter[]
    }): Promise<number> {
        const { teamId, properties } = teamPersons

        if (properties.length === 0) {
            // Count all non-deleted persons - matches HogQL: SELECT count(DISTINCT persons.id) FROM persons WHERE team_id = X
            const query = `
                SELECT count(DISTINCT id) as count
                FROM (
                    SELECT id
                    FROM person
                    FINAL
                    WHERE team_id = ${teamId}
                      AND is_deleted = 0
                    GROUP BY id, team_id
                )
            `
            const result = await this.query<{ count: string }>(query)
            return parseInt(result[0].count, 10)
        }

        // Build property filters - this generates the WHERE clause equivalent to HogQL's property_to_expr
        const propertyFilters = this.buildPropertyFilters(properties)

        // Match Python's HogQL structure: count(DISTINCT persons.id) with property filters in WHERE
        const query = `
            SELECT count(DISTINCT id) as count
            FROM (
                SELECT
                    id,
                    team_id,
                    argMax(properties, _timestamp) as properties
                FROM person
                FINAL
                WHERE team_id = ${teamId}
                  AND is_deleted = 0
                GROUP BY team_id, id
                HAVING ${propertyFilters}
            )
        `

        const result = await this.query<{ count: string }>(query)
        return parseInt(result[0].count, 10)
    }

    async fetchPersonsByProperties(teamPersons: {
        teamId: TeamId
        properties: PersonPropertyFilter[]
        options?: { limit?: number; cursor?: string }
    }): Promise<InternalPersonWithDistinctId[]> {
        const { teamId, properties, options } = teamPersons
        const limit = options?.limit ?? 100
        const cursor = options?.cursor

        // Build property filters
        const propertyFilters = this.buildPropertyFilters(properties)

        // Build cursor filter if provided
        const cursorFilter = cursor ? `AND id > '${escapeClickHouseString(cursor)}'` : ''

        const query = `
            SELECT
                p.id,
                p.team_id,
                p.is_identified,
                p.created_at,
                p.properties,
                p.version,
                pd.distinct_id
            FROM (
                SELECT
                    id,
                    team_id,
                    max(is_identified) as is_identified,
                    argMax(properties, _timestamp) as properties,
                    argMin(created_at, _timestamp) as created_at,
                    argMax(version, _timestamp) as version,
                    max(is_deleted) as is_deleted
                FROM person
                FINAL
                WHERE team_id = ${teamId}
                  ${cursorFilter}
                GROUP BY team_id, id
                HAVING is_deleted = 0
                  ${propertyFilters ? `AND ${propertyFilters}` : ''}
                ORDER BY id
                LIMIT ${limit}
            ) p
            LEFT JOIN (
                SELECT
                    team_id,
                    person_id,
                    any(distinct_id) as distinct_id
                FROM person_distinct_id2
                FINAL
                WHERE team_id = ${teamId}
                  AND is_deleted = 0
                GROUP BY team_id, person_id
            ) pd ON p.team_id = pd.team_id AND p.id = pd.person_id
        `

        const results = await this.query<ClickHousePersonWithDistinctId>(query)
        return results.map((row) => ({
            ...this.convertToInternalPerson(row),
            distinct_id: row.distinct_id,
        }))
    }

    createPerson(
        _createdAt: DateTime,
        _properties: Properties,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation,
        _teamId: Team['id'],
        _isUserId: number | null,
        _isIdentified: boolean,
        _uuid: string,
        _primaryDistinctId: { distinctId: string; version?: number },
        _extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    updatePerson(
        _person: InternalPerson,
        _update: PersonUpdateFields,
        _tag?: string
    ): Promise<[InternalPerson, TopicMessage[], boolean]> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    updatePersonAssertVersion(_personUpdate: PersonUpdate): Promise<[number | undefined, TopicMessage[]]> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    updatePersonsBatch(
        _personUpdates: PersonUpdate[]
    ): Promise<Map<string, { success: boolean; version?: number; kafkaMessage?: TopicMessage; error?: Error }>> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    deletePerson(_person: InternalPerson): Promise<TopicMessage[]> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    addDistinctId(_person: InternalPerson, _distinctId: string, _version: number): Promise<TopicMessage[]> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    addPersonlessDistinctId(_teamId: Team['id'], _distinctId: string): Promise<boolean> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    addPersonlessDistinctIdForMerge(_teamId: Team['id'], _distinctId: string): Promise<boolean> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    addPersonlessDistinctIdsBatch(_entries: { teamId: number; distinctId: string }[]): Promise<Map<string, boolean>> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    personPropertiesSize(_personId: string, _teamId: number): Promise<number> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    updateCohortsAndFeatureFlagsForMerge(
        _teamID: Team['id'],
        _sourcePersonID: InternalPerson['id'],
        _targetPersonID: InternalPerson['id']
    ): Promise<void> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    inTransaction<T>(_description: string, _transaction: (tx: PersonRepositoryTransaction) => Promise<T>): Promise<T> {
        throw new Error('Write operations not supported in ClickHousePersonRepository')
    }

    /**
     * Helper method to build property filter conditions for ClickHouse queries.
     * Matches the behavior of Python's property_to_expr for person properties.
     * Note: Does not support cohort properties - those require joins to cohort tables.
     */
    private buildPropertyFilters(properties: PersonPropertyFilter[]): string {
        if (properties.length === 0) {
            return ''
        }

        const filters = properties.map((filter) => {
            const { key, value, operator = 'exact' } = filter
            const escapedKey = escapeClickHouseString(key)

            // Normalize values to strings to match Python's _normalize_property_value behavior
            const normalizeValue = (val: any): string | null => {
                if (val === null || val === undefined) {
                    return null
                }
                return String(val)
            }

            switch (operator) {
                case 'exact': {
                    if (Array.isArray(value)) {
                        // List values use IN logic (match any value in the list)
                        const values = value
                            .map(normalizeValue)
                            .filter((v) => v !== null)
                            .map((v) => `'${escapeClickHouseString(v!)}'`)
                            .join(', ')
                        return `JSONExtractString(properties, '${escapedKey}') IN (${values})`
                    } else {
                        const normalizedValue = normalizeValue(value)
                        if (normalizedValue === null) {
                            return `JSONExtractString(properties, '${escapedKey}') = ''`
                        }
                        return `JSONExtractString(properties, '${escapedKey}') = '${escapeClickHouseString(normalizedValue)}'`
                    }
                }

                case 'is_not': {
                    if (Array.isArray(value)) {
                        // List values use NOT IN logic
                        const values = value
                            .map(normalizeValue)
                            .filter((v) => v !== null)
                            .map((v) => `'${escapeClickHouseString(v!)}'`)
                            .join(', ')
                        return `JSONExtractString(properties, '${escapedKey}') NOT IN (${values})`
                    } else {
                        const normalizedValue = normalizeValue(value)
                        if (normalizedValue === null) {
                            return `JSONExtractString(properties, '${escapedKey}') != ''`
                        }
                        return `JSONExtractString(properties, '${escapedKey}') != '${escapeClickHouseString(normalizedValue)}'`
                    }
                }

                case 'icontains': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "icontains" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=0' // Always false
                    }
                    return `positionCaseInsensitive(JSONExtractString(properties, '${escapedKey}'), '${escapeClickHouseString(normalizedValue)}') > 0`
                }

                case 'not_icontains': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "not_icontains" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=1' // Always true
                    }
                    return `positionCaseInsensitive(JSONExtractString(properties, '${escapedKey}'), '${escapeClickHouseString(normalizedValue)}') = 0`
                }

                case 'regex': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "regex" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=0' // Always false
                    }
                    return `match(JSONExtractString(properties, '${escapedKey}'), '${escapeClickHouseString(normalizedValue)}')`
                }

                case 'not_regex': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "not_regex" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=1' // Always true
                    }
                    return `NOT match(JSONExtractString(properties, '${escapedKey}'), '${escapeClickHouseString(normalizedValue)}')`
                }

                case 'gt': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "gt" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=0' // Always false
                    }
                    // Try to parse as number for proper comparison
                    return `toFloat64OrNull(JSONExtractString(properties, '${escapedKey}')) > ${parseFloat(normalizedValue)}`
                }

                case 'lt': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "lt" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=0' // Always false
                    }
                    // Try to parse as number for proper comparison
                    return `toFloat64OrNull(JSONExtractString(properties, '${escapedKey}')) < ${parseFloat(normalizedValue)}`
                }

                case 'is_set':
                    return `JSONHas(properties, '${escapedKey}')`

                case 'is_not_set':
                    return `NOT JSONHas(properties, '${escapedKey}')`

                case 'is_date_before': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "is_date_before" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=0' // Always false
                    }
                    // Date values should already be normalized to 'YYYY-MM-DD HH:MM:SS' format by replace_proxy_properties
                    return `toDateTime(JSONExtractString(properties, '${escapedKey}')) < toDateTime('${escapeClickHouseString(normalizedValue)}')`
                }

                case 'is_date_after': {
                    if (Array.isArray(value)) {
                        throw new Error('Operator "is_date_after" does not support list values')
                    }
                    const normalizedValue = normalizeValue(value)
                    if (normalizedValue === null) {
                        return '1=0' // Always false
                    }
                    // Date values should already be normalized to 'YYYY-MM-DD HH:MM:SS' format by replace_proxy_properties
                    return `toDateTime(JSONExtractString(properties, '${escapedKey}')) > toDateTime('${escapeClickHouseString(normalizedValue)}')`
                }

                default:
                    throw new Error(`Unsupported property filter operator: ${operator}`)
            }
        })

        return filters.join(' AND ')
    }

    /**
     * Convert ClickHouse person row to InternalPerson
     */
    private convertToInternalPerson(row: ClickHousePersonRow): InternalPerson {
        return {
            id: row.id,
            uuid: row.id,
            team_id: row.team_id,
            properties: parseJSON(row.properties),
            properties_last_updated_at: {},
            properties_last_operation: {},
            is_user_id: null,
            is_identified: Boolean(row.is_identified),
            created_at: DateTime.fromSQL(row.created_at, { zone: 'UTC' }),
            version: row.version || 0,
        }
    }

    /**
     * Execute a ClickHouse query and return results as JSON
     */
    private async query<T>(query: string): Promise<T[]> {
        return await this.clickHouseRouter.query<T>(query)
    }
}

/**
 * ClickHouse person row with aggregated fields
 */
interface ClickHousePersonRow {
    id: string
    team_id: number
    is_identified: number
    properties: string
    created_at: string
    version: number
}

/**
 * ClickHouse person row joined with distinct_id
 */
interface ClickHousePersonWithDistinctId extends ClickHousePersonRow {
    distinct_id: string
}
