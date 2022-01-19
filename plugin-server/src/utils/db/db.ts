import ClickHouse from '@posthog/clickhouse'
import { CacheOptions, Properties } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'
import { Pool as GenericPool } from 'generic-pool'
import { StatsD } from 'hot-shots'
import Redis from 'ioredis'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import {
    KAFKA_GROUPS,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_UNIQUE_ID,
    KAFKA_PLUGIN_LOG_ENTRIES,
} from '../../config/kafka-topics'
import {
    Action,
    ActionEventPair,
    ActionStep,
    ClickHouseEvent,
    ClickhouseGroup,
    ClickHousePerson,
    ClickHousePersonDistinctId,
    ClickHousePersonDistinctId2,
    Cohort,
    CohortPeople,
    Database,
    DeadLetterQueueEvent,
    Element,
    ElementGroup,
    Event,
    EventDefinitionType,
    EventPropertyType,
    Group,
    GroupTypeIndex,
    GroupTypeToColumnIndex,
    Hook,
    Person,
    PersonDistinctId,
    PluginConfig,
    PluginLogEntry,
    PluginLogEntrySource,
    PluginLogEntryType,
    PostgresSessionRecordingEvent,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    PropertyDefinitionType,
    PropertyUpdateOperation,
    RawAction,
    RawGroup,
    RawOrganization,
    RawPerson,
    SessionRecordingEvent,
    Team,
    TeamId,
    TimestampFormat,
} from '../../types'
import { instrumentQuery } from '../metrics'
import {
    castTimestampOrNow,
    clickHouseTimestampToISO,
    escapeClickHouseString,
    RaceConditionError,
    sanitizeSqlIdentifier,
    tryTwice,
    UUID,
    UUIDT,
} from '../utils'
import { OrganizationPluginsAccessLevel } from './../../types'
import { KafkaProducerWrapper } from './kafka-producer-wrapper'
import { PostgresLogsWrapper } from './postgres-logs-wrapper'
import {
    chainToElements,
    generateKafkaPersonUpdateMessage,
    generatePostgresValuesString,
    getFinalPostgresQuery,
    hashElements,
    timeoutGuard,
    unparsePersonPartial,
} from './utils'

export interface LogEntryPayload {
    pluginConfig: PluginConfig
    source: PluginLogEntrySource
    type: PluginLogEntryType
    message: string
    instanceId: UUID
    timestamp?: string | null
}

export interface ParsedLogEntry {
    id: string
    team_id: number
    plugin_id: number
    plugin_config_id: number
    timestamp: string
    source: PluginLogEntrySource
    type: PluginLogEntryType
    message: string
    instance_id: string
}

export interface CreateUserPayload {
    uuid: UUIDT
    password: string
    first_name: string
    last_name: string
    email: string
    distinct_id: string
    is_staff: boolean
    is_active: boolean
    date_joined: Date
    events_column_config: Record<string, string> | null
    organization_id?: RawOrganization['id']
}

export interface CreatePersonalApiKeyPayload {
    id: string
    user_id: number
    label: string
    value: string
    created_at: Date
}

/** The recommended way of accessing the database. */
export class DB {
    /** Postgres connection pool for primary database access. */
    postgres: Pool
    /** Redis used for various caches. */
    redisPool: GenericPool<Redis.Redis>

    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    kafkaProducer?: KafkaProducerWrapper
    /** ClickHouse used for syncing Postgres and ClickHouse person data. */
    clickhouse?: ClickHouse

    /** StatsD instance used to do instrumentation */
    statsd: StatsD | undefined

    /** A buffer for Postgres logs to prevent too many log insert ueries */
    postgresLogsWrapper: PostgresLogsWrapper

    /** How many unique group types to allow per team */
    MAX_GROUP_TYPES_PER_TEAM = 5

    /** Whether to write to clickhouse_person_unique_id topic */
    writeToPersonUniqueId?: boolean

    constructor(
        postgres: Pool,
        redisPool: GenericPool<Redis.Redis>,
        kafkaProducer: KafkaProducerWrapper | undefined,
        clickhouse: ClickHouse | undefined,
        statsd: StatsD | undefined
    ) {
        this.postgres = postgres
        this.redisPool = redisPool
        this.kafkaProducer = kafkaProducer
        this.clickhouse = clickhouse
        this.statsd = statsd
        this.postgresLogsWrapper = new PostgresLogsWrapper(this)
    }

    // Postgres

    public postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
        queryString: string,
        values: I | undefined,
        tag: string,
        client?: PoolClient
    ): Promise<QueryResult<R>> {
        return instrumentQuery(this.statsd, 'query.postgres', tag, async () => {
            let fullQuery = ''
            try {
                fullQuery = getFinalPostgresQuery(queryString, values as any[])
            } catch {}
            const timeout = timeoutGuard('Postgres slow query warning after 30 sec', {
                queryString,
                values,
                fullQuery,
            })

            // Annotate query string to give context when looking at DB logs
            queryString = `/* plugin-server:${tag} */ ${queryString}`
            try {
                if (client) {
                    return await client.query(queryString, values)
                } else {
                    return await this.postgres.query(queryString, values)
                }
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    public postgresTransaction<ReturnType extends any>(
        transaction: (client: PoolClient) => Promise<ReturnType>
    ): Promise<ReturnType> {
        return instrumentQuery(this.statsd, 'query.postgres_transation', undefined, async () => {
            const timeout = timeoutGuard(`Postgres slow transaction warning after 30 sec!`)
            const client = await this.postgres.connect()
            try {
                await client.query('BEGIN')
                const response = await transaction(client)
                await client.query('COMMIT')
                return response
            } catch (e) {
                await client.query('ROLLBACK')
                throw e
            } finally {
                client.release()
                clearTimeout(timeout)
            }
        })
    }

    // ClickHouse

    public clickhouseQuery(
        query: string,
        options?: ClickHouse.QueryOptions
    ): Promise<ClickHouse.QueryResult<Record<string, any>>> {
        return instrumentQuery(this.statsd, 'query.clickhouse', undefined, async () => {
            if (!this.clickhouse) {
                throw new Error('ClickHouse connection has not been provided to this DB instance!')
            }
            const timeout = timeoutGuard('ClickHouse slow query warning after 30 sec', { query })
            try {
                return await this.clickhouse.querying(query, options)
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    // Redis

    public redisGet(key: string, defaultValue: unknown, options: CacheOptions = {}): Promise<unknown> {
        const { jsonSerialize = true } = options

        return instrumentQuery(this.statsd, 'query.regisGet', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('Getting redis key delayed. Waiting over 30 sec to get key.', { key })
            try {
                const value = await tryTwice(
                    async () => await client.get(key),
                    `Waited 5 sec to get redis key: ${key}, retrying once!`
                )
                if (typeof value === 'undefined') {
                    return defaultValue
                }
                return value ? (jsonSerialize ? JSON.parse(value) : value) : null
            } catch (error) {
                if (error instanceof SyntaxError) {
                    // invalid JSON
                    return null
                } else {
                    throw error
                }
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisSet(key: string, value: unknown, ttlSeconds?: number, options: CacheOptions = {}): Promise<void> {
        const { jsonSerialize = true } = options

        return instrumentQuery(this.statsd, 'query.redisSet', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('Setting redis key delayed. Waiting over 30 sec to set key', { key })
            try {
                const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
                if (ttlSeconds) {
                    await client.set(key, serializedValue, 'EX', ttlSeconds)
                } else {
                    await client.set(key, serializedValue)
                }
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisIncr(key: string): Promise<number> {
        return instrumentQuery(this.statsd, 'query.redisIncr', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('Incrementing redis key delayed. Waiting over 30 sec to incr key', { key })
            try {
                return await client.incr(key)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisExpire(key: string, ttlSeconds: number): Promise<boolean> {
        return instrumentQuery(this.statsd, 'query.redisExpire', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('Expiring redis key delayed. Waiting over 30 sec to expire key', { key })
            try {
                return (await client.expire(key, ttlSeconds)) === 1
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisLPush(key: string, value: unknown, options: CacheOptions = {}): Promise<number> {
        const { jsonSerialize = true } = options

        return instrumentQuery(this.statsd, 'query.redisLPush', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('LPushing redis key delayed. Waiting over 30 sec to lpush key', { key })
            try {
                const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string | string[])
                return await client.lpush(key, serializedValue)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisLRange(key: string, startIndex: number, endIndex: number): Promise<string[]> {
        return instrumentQuery(this.statsd, 'query.redisLRange', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('LRANGE delayed. Waiting over 30 sec to perform LRANGE', {
                key,
                startIndex,
                endIndex,
            })
            try {
                return await client.lrange(key, startIndex, endIndex)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisLLen(key: string): Promise<number> {
        return instrumentQuery(this.statsd, 'query.redisLLen', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('LLEN delayed. Waiting over 30 sec to perform LLEN', {
                key,
            })
            try {
                return await client.llen(key)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisBRPop(key1: string, key2: string): Promise<[string, string]> {
        return instrumentQuery(this.statsd, 'query.redisBRPop', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('BRPoping redis key delayed. Waiting over 30 sec to brpop keys', {
                key1,
                key2,
            })
            try {
                return await client.brpop(key1, key2)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisLRem(key: string, count: number, elementKey: string): Promise<number> {
        return instrumentQuery(this.statsd, 'query.redisLRem', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('LREM delayed. Waiting over 30 sec to perform LREM', {
                key,
                count,
                elementKey,
            })
            try {
                return await client.lrem(key, count, elementKey)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    public redisLPop(key: string, count: number): Promise<string[]> {
        return instrumentQuery(this.statsd, 'query.redisLPop', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('LPOP delayed. Waiting over 30 sec to perform LPOP', {
                key,
                count,
            })
            try {
                return await client.lpop(key, count)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    // Person

    public async fetchPersons(database?: Database.Postgres): Promise<Person[]>
    public async fetchPersons(database: Database.ClickHouse): Promise<ClickHousePerson[]>
    public async fetchPersons(database: Database = Database.Postgres): Promise<Person[] | ClickHousePerson[]> {
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
            return (await this.clickhouseQuery(query)).data.map((row) => {
                const { 'person_max._timestamp': _discard1, 'person_max.id': _discard2, ...rest } = row
                return rest
            }) as ClickHousePerson[]
        } else if (database === Database.Postgres) {
            return (
                (await this.postgresQuery('SELECT * FROM posthog_person', undefined, 'fetchPersons'))
                    .rows as RawPerson[]
            ).map(
                (rawPerson: RawPerson) =>
                    ({
                        ...rawPerson,
                        created_at: DateTime.fromISO(rawPerson.created_at).toUTC(),
                        version: Number(rawPerson.version || 0),
                    } as Person)
            )
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
    }

    public async fetchPerson(
        teamId: number,
        distinctId: string,
        client?: PoolClient,
        options: { forUpdate?: boolean } = {}
    ): Promise<Person | undefined> {
        let queryString = `SELECT
                posthog_person.id, posthog_person.created_at, posthog_person.team_id, posthog_person.properties,
                posthog_person.properties_last_updated_at, posthog_person.properties_last_operation, posthog_person.is_user_id, posthog_person.is_identified,
                posthog_person.uuid, posthog_persondistinctid.team_id AS persondistinctid__team_id,
                posthog_persondistinctid.distinct_id AS persondistinctid__distinct_id
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

        const selectResult: QueryResult = await this.postgresQuery(queryString, values, 'fetchPerson', client)

        if (selectResult.rows.length > 0) {
            const rawPerson: RawPerson = selectResult.rows[0]
            return {
                ...rawPerson,
                created_at: DateTime.fromISO(rawPerson.created_at).toUTC(),
                version: Number(rawPerson.version || 0),
            }
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
        distinctIds?: string[]
    ): Promise<Person> {
        const kafkaMessages: ProducerRecord[] = []

        const person = await this.postgresTransaction(async (client) => {
            const insertResult = await this.postgresQuery(
                'INSERT INTO posthog_person (created_at, properties, properties_last_updated_at, properties_last_operation, team_id, is_user_id, is_identified, uuid, version) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING *',
                [
                    createdAt.toISO(),
                    JSON.stringify(properties),
                    JSON.stringify(propertiesLastUpdatedAt),
                    JSON.stringify(propertiesLastOperation),
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    0,
                ],
                'insertPerson',
                client
            )
            const personCreated = insertResult.rows[0] as RawPerson
            const person = {
                ...personCreated,
                created_at: DateTime.fromISO(personCreated.created_at).toUTC(),
                version: Number(personCreated.version || 0),
            } as Person

            if (this.kafkaProducer) {
                kafkaMessages.push(
                    generateKafkaPersonUpdateMessage(createdAt, properties, teamId, isIdentified, uuid, person.version)
                )
            }

            for (const distinctId of distinctIds || []) {
                const messages = await this.addDistinctIdPooled(person, distinctId, client)
                kafkaMessages.push(...messages)
            }

            return person
        })

        if (this.kafkaProducer) {
            await this.kafkaProducer.queueMessages(kafkaMessages)
        }

        return person
    }

    public async updatePersonDeprecated(
        person: Person,
        update: Partial<Person>,
        client: PoolClient
    ): Promise<ProducerRecord[]>
    public async updatePersonDeprecated(person: Person, update: Partial<Person>): Promise<Person>
    public async updatePersonDeprecated(
        person: Person,
        update: Partial<Person>,
        client?: PoolClient
    ): Promise<Person | ProducerRecord[]> {
        const updateValues = Object.values(unparsePersonPartial(update))

        // short circuit if there are no updates to be made
        if (updateValues.length === 0) {
            return client ? [] : person
        }

        const values = [...updateValues, person.id]

        const queryString = `UPDATE posthog_person SET version = COALESCE(version, 0)::numeric + 1, ${Object.keys(
            update
        ).map((field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`)} WHERE id = $${
            Object.values(update).length + 1
        }
        RETURNING version`

        const updateResult: QueryResult = await this.postgresQuery(queryString, values, 'updatePerson', client)
        if (updateResult.rows.length == 0) {
            throw new Error(`Person with team_id="${person.team_id}" and uuid="${person.uuid} couldn't be updated`)
        }
        const updatedPersonVersion: Person['version'] = Number(updateResult.rows[0].version)
        const updatedPerson: Person = { ...person, ...update, version: updatedPersonVersion }

        const kafkaMessages = []
        if (this.kafkaProducer) {
            const message = generateKafkaPersonUpdateMessage(
                updatedPerson.created_at,
                updatedPerson.properties,
                updatedPerson.team_id,
                updatedPerson.is_identified,
                updatedPerson.uuid,
                updatedPersonVersion
            )
            if (client) {
                kafkaMessages.push(message)
            } else {
                await this.kafkaProducer.queueMessage(message)
            }
        }

        return client ? kafkaMessages : updatedPerson
    }

    public async updatePerson(
        client: PoolClient,
        personId: number,
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number> {
        const updateResult: QueryResult = await this.postgresQuery(
            `UPDATE posthog_person SET
            created_at = $1,
            properties = $2,
            properties_last_updated_at = $3,
            properties_last_operation = $4,
            version = COALESCE(version, 0)::numeric + 1
        WHERE id = $5
        RETURNING version`,
            [
                createdAt.toISO(),
                JSON.stringify(properties),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
                personId,
            ],
            'updatePersonProperties',
            client
        )

        if (updateResult.rows.length === 0) {
            // this function should always be called in a transaction with person fetch locking for update before
            throw new RaceConditionError('Failed updating person properties')
        }
        return Number(updateResult.rows[0].version)
    }

    public async deletePerson(person: Person, client: PoolClient): Promise<ProducerRecord[]> {
        await client.query('DELETE FROM posthog_person WHERE team_id = $1 AND id = $2', [person.team_id, person.id])
        const kafkaMessages = []
        if (this.kafkaProducer) {
            kafkaMessages.push(
                generateKafkaPersonUpdateMessage(
                    person.created_at,
                    person.properties,
                    person.team_id,
                    person.is_identified,
                    person.uuid,
                    null,
                    1
                )
            )
        }
        return kafkaMessages
    }

    // PersonDistinctId

    public async fetchDistinctIds(person: Person, database?: Database.Postgres): Promise<PersonDistinctId[]>
    public async fetchDistinctIds(person: Person, database: Database.ClickHouse): Promise<ClickHousePersonDistinctId[]>
    public async fetchDistinctIds(
        person: Person,
        database: Database.ClickHouse,
        clichouseTable: 'person_distinct_id2'
    ): Promise<ClickHousePersonDistinctId2[]>
    public async fetchDistinctIds(
        person: Person,
        database: Database = Database.Postgres,
        clickhouseTable = 'person_distinct_id'
    ): Promise<PersonDistinctId[] | ClickHousePersonDistinctId[] | ClickHousePersonDistinctId2[]> {
        if (database === Database.ClickHouse) {
            return (
                await this.clickhouseQuery(
                    `
                        SELECT *
                        FROM ${clickhouseTable}
                        FINAL
                        WHERE person_id='${escapeClickHouseString(person.uuid)}'
                          AND team_id='${person.team_id}'
                          AND is_deleted=0
                        ORDER BY _offset`
                )
            ).data as ClickHousePersonDistinctId[]
        } else if (database === Database.Postgres) {
            const result = await this.postgresQuery(
                'SELECT * FROM posthog_persondistinctid WHERE person_id=$1 AND team_id=$2 ORDER BY id',
                [person.id, person.team_id],
                'fetchDistinctIds'
            )
            return result.rows as PersonDistinctId[]
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
    }

    public async fetchDistinctIdValues(person: Person, database: Database = Database.Postgres): Promise<string[]> {
        const personDistinctIds = await this.fetchDistinctIds(person, database as any)
        return personDistinctIds.map((pdi) => pdi.distinct_id)
    }

    public async addDistinctId(person: Person, distinctId: string): Promise<void> {
        const kafkaMessages = await this.addDistinctIdPooled(person, distinctId)
        if (this.kafkaProducer && kafkaMessages.length) {
            await this.kafkaProducer.queueMessages(kafkaMessages)
        }
    }

    public async addDistinctIdPooled(
        person: Person,
        distinctId: string,
        client?: PoolClient
    ): Promise<ProducerRecord[]> {
        const insertResult = await this.postgresQuery(
            'INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version) VALUES ($1, $2, $3, 0) RETURNING *',
            [distinctId, person.id, person.team_id],
            'addDistinctIdPooled',
            client
        )

        const { id, version: versionStr, ...personDistinctIdCreated } = insertResult.rows[0] as PersonDistinctId
        if (this.kafkaProducer) {
            const version = Number(versionStr || 0)
            const messages = [
                {
                    topic: KAFKA_PERSON_DISTINCT_ID,
                    messages: [
                        {
                            value: Buffer.from(
                                JSON.stringify({
                                    ...personDistinctIdCreated,
                                    version,
                                    person_id: person.uuid,
                                    is_deleted: 0,
                                })
                            ),
                        },
                    ],
                },
            ]

            if (await this.fetchWriteToPersonUniqueId()) {
                messages.push({
                    topic: KAFKA_PERSON_UNIQUE_ID,
                    messages: [
                        {
                            value: Buffer.from(
                                JSON.stringify({
                                    ...personDistinctIdCreated,
                                    person_id: person.uuid,
                                    is_deleted: 0,
                                })
                            ),
                        },
                    ],
                })
            }

            return messages
        } else {
            return []
        }
    }

    public async moveDistinctIds(source: Person, target: Person, client?: PoolClient): Promise<ProducerRecord[]> {
        let movedDistinctIdResult: QueryResult<any> | null = null
        try {
            movedDistinctIdResult = await this.postgresQuery(
                `
                    UPDATE posthog_persondistinctid
                    SET person_id = $1, version = COALESCE(version, 0)::numeric + 1
                    WHERE person_id = $2
                      AND team_id = $3
                    RETURNING *
                `,
                [target.id, source.id, target.team_id],
                'updateDistinctIdPerson',
                client
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
        if (this.kafkaProducer) {
            for (const row of movedDistinctIdResult.rows) {
                const { id, version: versionStr, ...usefulColumns } = row as PersonDistinctId
                const version = Number(versionStr || 0)
                kafkaMessages.push({
                    topic: KAFKA_PERSON_DISTINCT_ID,
                    messages: [
                        {
                            value: Buffer.from(
                                JSON.stringify({ ...usefulColumns, version, person_id: target.uuid, is_deleted: 0 })
                            ),
                        },
                    ],
                })

                if (await this.fetchWriteToPersonUniqueId()) {
                    kafkaMessages.push({
                        topic: KAFKA_PERSON_UNIQUE_ID,
                        messages: [
                            {
                                value: Buffer.from(
                                    JSON.stringify({ ...usefulColumns, person_id: target.uuid, is_deleted: 0 })
                                ),
                            },
                            {
                                value: Buffer.from(
                                    JSON.stringify({ ...usefulColumns, person_id: source.uuid, is_deleted: 1 })
                                ),
                            },
                        ],
                    })
                }
            }
        }
        return kafkaMessages
    }

    // Cohort & CohortPeople
    // testutil
    public async createCohort(cohort: Partial<Cohort>): Promise<Cohort> {
        const insertResult = await this.postgresQuery(
            `INSERT INTO posthog_cohort (name, description, deleted, groups, team_id, created_at, created_by_id, is_calculating, last_calculation,errors_calculating, is_static) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING *;`,
            [
                cohort.name,
                cohort.description,
                cohort.deleted ?? false,
                cohort.groups ?? [],
                cohort.team_id,
                cohort.created_at ?? new Date().toISOString(),
                cohort.created_by_id,
                cohort.is_calculating ?? false,
                cohort.last_calculation ?? new Date().toISOString(),
                cohort.errors_calculating ?? 0,
                cohort.is_static ?? false,
            ],
            'createCohort'
        )
        return insertResult.rows[0]
    }

    public async doesPersonBelongToCohort(cohortId: number, person: Person, teamId: Team['id']): Promise<boolean> {
        if (this.kafkaProducer) {
            const chResult = await this.clickhouseQuery(
                `SELECT 1 FROM person_static_cohort
                WHERE
                    team_id = ${teamId}
                    AND cohort_id = ${cohortId}
                    AND person_id = '${escapeClickHouseString(person.uuid)}'
                LIMIT 1`
            )

            if (chResult.rows > 0) {
                // Cohort is static and our person belongs to it
                return true
            }
        }

        const psqlResult = await this.postgresQuery(
            `SELECT EXISTS (SELECT 1 FROM posthog_cohortpeople WHERE cohort_id = $1 AND person_id = $2);`,
            [cohortId, person.id],
            'doesPersonBelongToCohort'
        )
        return psqlResult.rows[0].exists
    }

    public async addPersonToCohort(cohortId: number, personId: Person['id']): Promise<CohortPeople> {
        const insertResult = await this.postgresQuery(
            `INSERT INTO posthog_cohortpeople (cohort_id, person_id) VALUES ($1, $2) RETURNING *;`,
            [cohortId, personId],
            'addPersonToCohort'
        )
        return insertResult.rows[0]
    }

    // Event

    public async fetchEvents(): Promise<Event[] | ClickHouseEvent[]> {
        if (this.kafkaProducer) {
            const events = (await this.clickhouseQuery(`SELECT * FROM events ORDER BY timestamp ASC`))
                .data as ClickHouseEvent[]
            return (
                events?.map(
                    (event) =>
                        ({
                            ...event,
                            ...(typeof event['properties'] === 'string'
                                ? { properties: JSON.parse(event.properties) }
                                : {}),
                            timestamp: clickHouseTimestampToISO(event.timestamp),
                        } as ClickHouseEvent)
                ) || []
            )
        } else {
            const result = await this.postgresQuery(
                'SELECT * FROM posthog_event ORDER BY timestamp ASC',
                undefined,
                'fetchAllEvents'
            )
            return result.rows as Event[]
        }
    }

    public async fetchDeadLetterQueueEvents(): Promise<DeadLetterQueueEvent[]> {
        const result = await this.clickhouseQuery(`SELECT * FROM events_dead_letter_queue ORDER BY _timestamp ASC`)
        const events = result.data as DeadLetterQueueEvent[]
        return events
    }

    // SessionRecordingEvent

    public async fetchSessionRecordingEvents(): Promise<PostgresSessionRecordingEvent[] | SessionRecordingEvent[]> {
        if (this.kafkaProducer) {
            const events = (
                (await this.clickhouseQuery(`SELECT * FROM session_recording_events`)).data as SessionRecordingEvent[]
            ).map((event) => {
                return {
                    ...event,
                    snapshot_data: event.snapshot_data ? JSON.parse(event.snapshot_data) : null,
                }
            })
            return events
        } else {
            const result = await this.postgresQuery(
                'SELECT * FROM posthog_sessionrecordingevent',
                undefined,
                'fetchAllSessionRecordingEvents'
            )
            return result.rows as PostgresSessionRecordingEvent[]
        }
    }

    // Element

    public async fetchElements(event?: Event): Promise<Element[]> {
        if (this.kafkaProducer) {
            const events = (
                await this.clickhouseQuery(
                    `SELECT elements_chain FROM events WHERE uuid='${escapeClickHouseString((event as any).uuid)}'`
                )
            ).data as ClickHouseEvent[]
            const chain = events?.[0]?.elements_chain
            return chainToElements(chain)
        } else {
            return (await this.postgresQuery('SELECT * FROM posthog_element', undefined, 'fetchAllElements')).rows
        }
    }

    public async fetchPostgresElementsByHash(teamId: number, elementsHash: string): Promise<Record<string, any>[]> {
        const cachedResult = await this.redisGet(elementsHash, null)

        let result: Record<string, any>[]

        if (cachedResult) {
            result = JSON.parse(String(cachedResult))
        } else {
            result = (
                await this.postgresQuery(
                    `
                SELECT text, tag_name, href, attr_id, nth_child, nth_of_type, attributes, attr_class
                FROM posthog_element
                LEFT JOIN posthog_elementgroup on posthog_element.group_id = posthog_elementgroup.id
                WHERE
                    posthog_elementgroup.team_id=$1 AND
                    posthog_elementgroup.hash=$2
                ORDER BY posthog_element.order
                `,
                    [teamId, elementsHash],
                    'fetchPostgresElementsByHash'
                )
            ).rows

            await this.redisSet(elementsHash, JSON.stringify(result), 60 * 2) // 2 hour TTL
        }

        return result
    }

    public async createElementGroup(elements: Element[], teamId: number): Promise<string> {
        const cleanedElements = elements.map((element, index) => ({ ...element, order: index }))
        const hash = hashElements(cleanedElements)

        try {
            await this.postgresTransaction(async (client) => {
                const insertResult = await this.postgresQuery(
                    'INSERT INTO posthog_elementgroup (hash, team_id) VALUES ($1, $2) ON CONFLICT DO NOTHING RETURNING *',
                    [hash, teamId],
                    'createElementGroup',
                    client
                )

                if (insertResult.rows.length > 0) {
                    const ELEMENTS_TABLE_COLUMN_COUNT = 11
                    const elementGroup = insertResult.rows[0] as ElementGroup
                    const values = []
                    const rowStrings = []

                    for (let rowIndex = 0; rowIndex < cleanedElements.length; ++rowIndex) {
                        const {
                            text,
                            tag_name,
                            href,
                            attr_id,
                            nth_child,
                            nth_of_type,
                            attributes,
                            order,
                            event_id,
                            attr_class,
                        } = cleanedElements[rowIndex]

                        rowStrings.push(generatePostgresValuesString(ELEMENTS_TABLE_COLUMN_COUNT, rowIndex))

                        values.push(
                            text,
                            tag_name,
                            href,
                            attr_id,
                            nth_child,
                            nth_of_type,
                            attributes || {},
                            order,
                            event_id,
                            attr_class,
                            elementGroup.id
                        )
                    }

                    await this.postgresQuery(
                        `INSERT INTO posthog_element (text, tag_name, href, attr_id, nth_child, nth_of_type, attributes, "order", event_id, attr_class, group_id) VALUES ${rowStrings.join(
                            ', '
                        )}`,
                        values,
                        'insertElement',
                        client
                    )
                }
            })
        } catch (error) {
            // Throw further if not postgres error nr "23505" == "unique_violation"
            // https://www.postgresql.org/docs/12/errcodes-appendix.html
            if ((error as any).code !== '23505') {
                throw error
            }
        }

        return hash
    }

    // PluginLogEntry

    public async fetchPluginLogEntries(): Promise<PluginLogEntry[]> {
        if (this.kafkaProducer) {
            return (await this.clickhouseQuery(`SELECT * FROM plugin_log_entries`)).data as PluginLogEntry[]
        } else {
            return (await this.postgresQuery('SELECT * FROM posthog_pluginlogentry', undefined, 'fetchAllPluginLogs'))
                .rows as PluginLogEntry[]
        }
    }

    public async queuePluginLogEntry(entry: LogEntryPayload): Promise<void> {
        const { pluginConfig, source, message, type, timestamp, instanceId } = entry

        const parsedEntry = {
            id: new UUIDT().toString(),
            team_id: pluginConfig.team_id,
            plugin_id: pluginConfig.plugin_id,
            plugin_config_id: pluginConfig.id,
            timestamp: (timestamp || new Date().toISOString()).replace('T', ' ').replace('Z', ''),
            source,
            type,
            message,
            instance_id: instanceId.toString(),
        }

        this.statsd?.increment(`logs.entries_created`, {
            source,
            team_id: pluginConfig.team_id.toString(),
            plugin_id: pluginConfig.plugin_id.toString(),
        })

        if (this.kafkaProducer) {
            try {
                await this.kafkaProducer.queueMessage({
                    topic: KAFKA_PLUGIN_LOG_ENTRIES,
                    messages: [{ key: parsedEntry.id, value: Buffer.from(JSON.stringify(parsedEntry)) }],
                })
            } catch (e) {
                captureException(e)
                console.error(parsedEntry)
                console.error(e)
            }
        } else {
            await this.postgresLogsWrapper.addLog(parsedEntry)
        }
    }

    public async batchInsertPostgresLogs(entries: ParsedLogEntry[]): Promise<void> {
        const LOG_ENTRY_COLUMN_COUNT = 9

        const rowStrings: string[] = []
        const values: any[] = []

        for (let rowIndex = 0; rowIndex < entries.length; ++rowIndex) {
            const { id, team_id, plugin_id, plugin_config_id, timestamp, source, type, message, instance_id } =
                entries[rowIndex]

            rowStrings.push(generatePostgresValuesString(LOG_ENTRY_COLUMN_COUNT, rowIndex))

            values.push(id, team_id, plugin_id, plugin_config_id, timestamp, source, type, message, instance_id)
        }
        try {
            await this.postgresQuery(
                `INSERT INTO posthog_pluginlogentry
                (id, team_id, plugin_id, plugin_config_id, timestamp, source, type, message, instance_id)
                VALUES
                ${rowStrings.join(', ')}`,
                values,
                'insertPluginLogEntries'
            )
        } catch (e) {
            captureException(e)
            console.error(e)
        }
    }

    // EventDefinition

    public async fetchEventDefinitions(): Promise<EventDefinitionType[]> {
        return (await this.postgresQuery('SELECT * FROM posthog_eventdefinition', undefined, 'fetchEventDefinitions'))
            .rows as EventDefinitionType[]
    }

    // PropertyDefinition

    public async fetchPropertyDefinitions(): Promise<PropertyDefinitionType[]> {
        return (
            await this.postgresQuery('SELECT * FROM posthog_propertydefinition', undefined, 'fetchPropertyDefinitions')
        ).rows as PropertyDefinitionType[]
    }

    // EventProperty

    public async fetchEventProperties(): Promise<EventPropertyType[]> {
        return (await this.postgresQuery('SELECT * FROM posthog_eventproperty', undefined, 'fetchEventProperties'))
            .rows as EventPropertyType[]
    }

    // Action & ActionStep & Action<>Event

    public async fetchAllActionsGroupedByTeam(): Promise<Record<Team['id'], Record<Action['id'], Action>>> {
        const rawActions: RawAction[] = (
            await this.postgresQuery(`SELECT * FROM posthog_action WHERE deleted = FALSE`, undefined, 'fetchActions')
        ).rows
        const actionSteps: (ActionStep & { team_id: Team['id'] })[] = (
            await this.postgresQuery(
                `SELECT posthog_actionstep.*, posthog_action.team_id
                    FROM posthog_actionstep JOIN posthog_action ON (posthog_action.id = posthog_actionstep.action_id)
                    WHERE posthog_action.deleted = FALSE`,
                undefined,
                'fetchActionSteps'
            )
        ).rows
        const actions: Record<Team['id'], Record<Action['id'], Action>> = {}
        for (const rawAction of rawActions) {
            if (!actions[rawAction.team_id]) {
                actions[rawAction.team_id] = {}
            }
            actions[rawAction.team_id][rawAction.id] = { ...rawAction, steps: [] }
        }
        for (const actionStep of actionSteps) {
            if (actions[actionStep.team_id]?.[actionStep.action_id]) {
                actions[actionStep.team_id][actionStep.action_id].steps.push(actionStep)
            }
        }
        return actions
    }

    public async fetchAction(id: Action['id']): Promise<Action | null> {
        const rawActions: RawAction[] = (
            await this.postgresQuery(
                `SELECT * FROM posthog_action WHERE id = $1 AND deleted = FALSE`,
                [id],
                'fetchActions'
            )
        ).rows
        if (!rawActions.length) {
            return null
        }
        const steps: ActionStep[] = (
            await this.postgresQuery(`SELECT * FROM posthog_actionstep WHERE action_id = $1`, [id], 'fetchActionSteps')
        ).rows
        const action: Action = { ...rawActions[0], steps }
        return action
    }

    public async fetchActionMatches(): Promise<ActionEventPair[]> {
        const result = await this.postgresQuery<ActionEventPair>(
            'SELECT * FROM posthog_action_events',
            undefined,
            'fetchActionMatches'
        )
        return result.rows
    }

    public async registerActionMatch(eventId: Event['id'], actions: Action[]): Promise<void> {
        const valuesClause = actions.map((action, index) => `($1, $${index + 2})`).join(', ')
        await this.postgresQuery(
            `INSERT INTO posthog_action_events (event_id, action_id) VALUES ${valuesClause}`,
            [eventId, ...actions.map((action) => action.id)],
            'registerActionMatch'
        )
    }

    // Organization

    public async fetchOrganization(organizationId: string): Promise<RawOrganization | undefined> {
        const selectResult = await this.postgresQuery<RawOrganization>(
            `SELECT * FROM posthog_organization WHERE id = $1`,
            [organizationId],
            'fetchOrganization'
        )
        return selectResult.rows[0]
    }

    // Team

    public async fetchTeam(teamId: Team['id']): Promise<Team> {
        const selectResult = await this.postgresQuery<Team>(
            `SELECT * FROM posthog_team WHERE id = $1`,
            [teamId],
            'fetchTeam'
        )
        return selectResult.rows[0]
    }

    public async fetchAsyncMigrationComplete(migrationName: string): Promise<boolean> {
        const { rows } = await this.postgresQuery(
            `
            SELECT name
            FROM posthog_asyncmigration
            WHERE name = $1 AND status = 2
            `,
            [migrationName],
            'fetchAsyncMigrationComplete'
        )
        return rows.length > 0
    }

    public async fetchWriteToPersonUniqueId(): Promise<boolean> {
        if (this.writeToPersonUniqueId === undefined) {
            this.writeToPersonUniqueId = !(await this.fetchAsyncMigrationComplete('0003_fill_person_distinct_id2'))
        }
        return this.writeToPersonUniqueId as boolean
    }

    /** Return the ID of the team that is used exclusively internally by the instance for storing metrics data. */
    public async fetchInternalMetricsTeam(): Promise<Team['id'] | null> {
        const { rows } = await this.postgresQuery(
            `
            SELECT posthog_team.id AS team_id
            FROM posthog_team
            INNER JOIN posthog_organization ON posthog_organization.id = posthog_team.organization_id
            WHERE for_internal_metrics`,
            undefined,
            'fetchInternalMetricsTeam'
        )

        return rows[0]?.team_id || null
    }

    // Hook (EE)

    public async fetchRelevantRestHooks(
        teamId: Hook['team_id'],
        event: Hook['event'],
        resourceId: Hook['resource_id']
    ): Promise<Hook[]> {
        const filterByResource = resourceId !== null
        const { rows } = await this.postgresQuery<Hook>(
            `
            SELECT * FROM ee_hook
            WHERE team_id = $1 AND event = $2 ${filterByResource ? 'AND resource_id = $3' : ''}`,
            filterByResource ? [teamId, event, resourceId] : [teamId, event],
            'fetchRelevantRestHooks'
        )
        return rows
    }

    public async deleteRestHook(hookId: Hook['id']): Promise<void> {
        await this.postgresQuery(`DELETE FROM ee_hook WHERE id = $1`, [hookId], 'deleteRestHook')
    }

    public async createUser({
        uuid,
        password,
        first_name,
        last_name,
        email,
        distinct_id,
        is_staff,
        is_active,
        date_joined,
        events_column_config,
        organization_id,
    }: CreateUserPayload): Promise<QueryResult> {
        const createUserResult = await this.postgresQuery(
            `INSERT INTO posthog_user (uuid, password, first_name, last_name, email, distinct_id, is_staff, is_active, date_joined, events_column_config)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id`,
            [
                uuid.toString(),
                password,
                first_name,
                last_name,
                email,
                distinct_id,
                is_staff,
                is_active,
                date_joined.toISOString(),
                events_column_config,
            ],
            'createUser'
        )

        if (organization_id) {
            const now = new Date().toISOString()
            await this.postgresQuery(
                `INSERT INTO posthog_organizationmembership (id, organization_id, user_id, level, joined_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)`,
                [new UUIDT().toString(), organization_id, createUserResult.rows[0].id, 1, now, now],
                'createOrganizationMembership'
            )
        }

        return createUserResult
    }

    public async createPersonalApiKey({
        id,
        user_id,
        label,
        value,
        created_at,
    }: CreatePersonalApiKeyPayload): Promise<QueryResult> {
        return await this.postgresQuery(
            `INSERT INTO posthog_personalapikey (id, user_id, label, value, created_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING value`,
            [id, user_id, label, value, created_at.toISOString()],
            'createPersonalApiKey'
        )
    }

    public async fetchGroupTypes(teamId: TeamId): Promise<GroupTypeToColumnIndex> {
        const { rows } = await this.postgresQuery(
            `SELECT * FROM posthog_grouptypemapping WHERE team_id = $1`,
            [teamId],
            'fetchGroupTypes'
        )

        const result: GroupTypeToColumnIndex = {}

        for (const row of rows) {
            result[row.group_type] = row.group_type_index
        }

        return result
    }

    public async insertGroupType(
        teamId: TeamId,
        groupType: string,
        index: number
    ): Promise<[GroupTypeIndex | null, boolean]> {
        if (index >= this.MAX_GROUP_TYPES_PER_TEAM) {
            return [null, false]
        }

        const insertGroupTypeResult = await this.postgresQuery(
            `
            WITH insert_result AS (
                INSERT INTO posthog_grouptypemapping (team_id, group_type, group_type_index)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                RETURNING group_type_index
            )
            SELECT group_type_index, 1 AS is_insert  FROM insert_result
            UNION
            SELECT group_type_index, 0 AS is_insert FROM posthog_grouptypemapping WHERE team_id = $1 AND group_type = $2;
            `,
            [teamId, groupType, index],
            'insertGroupType'
        )

        if (insertGroupTypeResult.rows.length == 0) {
            return await this.insertGroupType(teamId, groupType, index + 1)
        }

        const { group_type_index, is_insert } = insertGroupTypeResult.rows[0]

        return [group_type_index, is_insert === 1]
    }

    public async fetchGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        client?: PoolClient,
        options: { forUpdate?: boolean } = {}
    ): Promise<Group | undefined> {
        let queryString = `SELECT * FROM posthog_group WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3`

        if (options.forUpdate) {
            queryString = queryString.concat(` FOR UPDATE`)
        }

        const selectResult: QueryResult = await this.postgresQuery(
            queryString,
            [teamId, groupTypeIndex, groupKey],
            'fetchGroup',
            client
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

    public async insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        version: number,
        client?: PoolClient
    ): Promise<void> {
        const result = await this.postgresQuery(
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
            'upsertGroup',
            client
        )

        if (result.rows.length === 0) {
            throw new RaceConditionError('Parallel posthog_group inserts, retry')
        }
    }

    public async updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        version: number,
        client?: PoolClient
    ): Promise<void> {
        await this.postgresQuery(
            `
            UPDATE posthog_group SET
            created_at = $4,
            group_properties = $5,
            properties_last_updated_at = $6,
            properties_last_operation = $7,
            version = $8
            WHERE team_id = $1 AND group_key = $2 AND group_type_index = $3
            `,
            [
                teamId,
                groupKey,
                groupTypeIndex,
                createdAt.toISO(),
                JSON.stringify(groupProperties),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
                version,
            ],
            'upsertGroup',
            client
        )
    }

    public async upsertGroupClickhouse(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        version: number
    ): Promise<void> {
        if (this.kafkaProducer) {
            await this.kafkaProducer.queueMessage({
                topic: KAFKA_GROUPS,
                messages: [
                    {
                        value: Buffer.from(
                            JSON.stringify({
                                group_type_index: groupTypeIndex,
                                group_key: groupKey,
                                team_id: teamId,
                                group_properties: JSON.stringify(properties),
                                created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouseSecondPrecision),
                                version,
                            })
                        ),
                    },
                ],
            })
        }
    }

    // Used in tests
    public async fetchClickhouseGroups(): Promise<ClickhouseGroup[]> {
        const query = `
        SELECT group_type_index, group_key, created_at, team_id, group_properties FROM groups FINAL
        `
        return (await this.clickhouseQuery(query)).data as ClickhouseGroup[]
    }

    public async getTeamsInOrganizationsWithRootPluginAccess(): Promise<Team[]> {
        return (
            await this.postgresQuery(
                'SELECT * from posthog_team WHERE organization_id = (SELECT id from posthog_organization WHERE plugins_access_level = $1)',
                [OrganizationPluginsAccessLevel.ROOT],
                'getTeamsInOrganizationsWithRootPluginAccess'
            )
        ).rows as Team[]
    }
}
