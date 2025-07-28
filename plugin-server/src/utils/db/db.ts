import ClickHouse from '@posthog/clickhouse'
import { CacheOptions, Properties } from '@posthog/plugin-scaffold'
import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'
import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import { KAFKA_GROUPS, KAFKA_PLUGIN_LOG_ENTRIES } from '../../config/kafka-topics'
import { KafkaProducerWrapper, TopicMessage } from '../../kafka/producer'
import {
    Action,
    ClickHouseEvent,
    ClickhouseGroup,
    ClickHousePerson,
    ClickHousePersonDistinctId2,
    ClickHouseTimestamp,
    Cohort,
    CohortPeople,
    Database,
    DeadLetterQueueEvent,
    Group,
    GroupKey,
    GroupTypeIndex,
    InternalPerson,
    OrganizationMembershipLevel,
    PersonDistinctId,
    Plugin,
    PluginConfig,
    PluginLogEntry,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginLogLevel,
    ProjectId,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    RawClickHouseEvent,
    RawGroup,
    RawOrganization,
    RawPerson,
    RawSessionRecordingEvent,
    Team,
    TeamId,
    TimestampFormat,
} from '../../types'
import { fetchAction, fetchAllActionsGroupedByTeam } from '../../worker/ingestion/action-manager'
import { parseRawClickHouseEvent } from '../event'
import { parseJSON } from '../json-parse'
import { logger } from '../logger'
import { instrumentQuery } from '../metrics'
import { captureException } from '../posthog'
import { castTimestampOrNow, escapeClickHouseString, RaceConditionError, tryTwice, UUID, UUIDT } from '../utils'
import { OrganizationPluginsAccessLevel } from './../../types'
import { RedisOperationError } from './error'
import { pluginLogEntryCounter } from './metrics'
import { PostgresRouter, PostgresUse, TransactionClient } from './postgres'
import { safeClickhouseString, shouldStoreLog, timeoutGuard } from './utils'

export type MoveDistinctIdsResult =
    | { readonly success: true; readonly messages: TopicMessage[]; readonly distinctIdsMoved: string[] }
    | { readonly success: false; readonly error: 'TargetNotFound' }
    | { readonly success: false; readonly error: 'SourceNotFound' }

export type CreatePersonResult =
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: TopicMessage[]
          readonly created: true
      }
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: TopicMessage[]
          readonly created: false
      }
    | { readonly success: false; readonly error: 'CreationConflict'; readonly distinctIds: string[] }

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
    organizationMembershipLevel?: number
}

export interface CreatePersonalApiKeyPayload {
    id: string
    user_id: number
    label: string
    secure_value: string
    created_at: Date
}

export type GroupId = [GroupTypeIndex, GroupKey]

export interface CachedGroupData {
    properties: Properties
    created_at: ClickHouseTimestamp
}

export interface PersonPropertiesSize {
    total_props_bytes: number
}

export const POSTGRES_UNAVAILABLE_ERROR_MESSAGES = [
    'connection to server at',
    'could not translate host',
    'server conn crashed',
    'no more connections allowed',
    'server closed the connection unexpectedly',
    'getaddrinfo EAI_AGAIN',
    'Connection terminated unexpectedly',
    'ECONNREFUSED',
    'ETIMEDOUT',
    'query_wait_timeout', // Waiting on PG bouncer to give us a slot
]

/** The recommended way of accessing the database. */
export class DB {
    /** Postgres connection router for database access. */
    postgres: PostgresRouter
    /** Redis used for various caches. */
    redisPool: GenericPool<Redis.Redis>

    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    kafkaProducer: KafkaProducerWrapper
    /** ClickHouse used for syncing Postgres and ClickHouse person data. */
    clickhouse: ClickHouse

    /** Default log level for plugins that don't specify it */
    pluginsDefaultLogLevel: PluginLogLevel

    /** How many seconds to keep person info in Redis cache */
    PERSONS_AND_GROUPS_CACHE_TTL: number

    constructor(
        postgres: PostgresRouter,
        redisPool: GenericPool<Redis.Redis>,
        kafkaProducer: KafkaProducerWrapper,
        clickhouse: ClickHouse,
        pluginsDefaultLogLevel: PluginLogLevel,
        personAndGroupsCacheTtl = 1
    ) {
        this.postgres = postgres
        this.redisPool = redisPool
        this.kafkaProducer = kafkaProducer
        this.clickhouse = clickhouse
        this.pluginsDefaultLogLevel = pluginsDefaultLogLevel
        this.PERSONS_AND_GROUPS_CACHE_TTL = personAndGroupsCacheTtl
    }

    // ClickHouse

    public clickhouseQuery<R extends Record<string, any> = Record<string, any>>(
        query: string,
        options?: ClickHouse.QueryOptions
    ): Promise<ClickHouse.ObjectQueryResult<R>> {
        return instrumentQuery('query.clickhouse', undefined, async () => {
            const timeout = timeoutGuard('ClickHouse slow query warning after 30 sec', { query })
            try {
                const queryResult = await this.clickhouse.querying(query, options)
                // This is annoying to type, because the result depends on contructor and query options provided
                // at runtime. However, with our options we can safely assume ObjectQueryResult<R>
                return queryResult as unknown as ClickHouse.ObjectQueryResult<R>
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    // Redis

    private instrumentRedisQuery<T>(
        operationName: string,
        tag: string | undefined,
        logContext: Record<string, string | string[] | number>,
        runQuery: (client: Redis.Redis) => Promise<T>
    ): Promise<T> {
        return instrumentQuery(operationName, tag, async () => {
            let client: Redis.Redis
            const timeout = timeoutGuard(`${operationName} delayed. Waiting over 30 sec.`, logContext)
            try {
                client = await this.redisPool.acquire()
            } catch (error) {
                throw new RedisOperationError('Failed to acquire redis client from pool', error, operationName)
            }

            // Don't use a single try/catch/finally for this, as there are 2 potential errors that could be thrown
            // (error and cleanup) and we want to be explicit about which one we choose, rather than relying on
            // "what happens when you throw in a finally block".
            // We explicitly want to throw the error from the operation if there is one, prioritising it over any errors
            // from the cleanup
            let operationResult: { value: T } | { error: Error }
            let cleanupError: Error | undefined

            try {
                operationResult = { value: await runQuery(client) }
            } catch (error) {
                operationResult = { error }
            }

            try {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            } catch (error) {
                cleanupError = error
            }

            if ('error' in operationResult) {
                throw new RedisOperationError(
                    `${operationName} failed for ${JSON.stringify(logContext)}`,
                    operationResult.error,
                    operationName,
                    logContext
                )
            }
            if (cleanupError) {
                throw new RedisOperationError('Failed to release redis client from pool', cleanupError, operationName)
            }
            return operationResult.value
        })
    }

    public redisGet<T = unknown>(
        key: string,
        defaultValue: T,
        tag: string,
        options: CacheOptions = {}
    ): Promise<T | null> {
        const { jsonSerialize = true } = options
        return this.instrumentRedisQuery('query.redisGet', tag, { key }, async (client) => {
            try {
                const value = await tryTwice(
                    async () => await client.get(key),
                    `Waited 5 sec to get redis key: ${key}, retrying once!`
                )
                if (typeof value === 'undefined' || value === null) {
                    return defaultValue
                }
                return value ? (jsonSerialize ? parseJSON(value) : value) : null
            } catch (error) {
                if (error instanceof SyntaxError) {
                    // invalid JSON
                    return null
                } else {
                    throw error
                }
            }
        })
    }

    public redisGetBuffer(key: string, tag: string): Promise<Buffer | null> {
        return this.instrumentRedisQuery('query.redisGetBuffer', tag, { key }, async (client) => {
            return await tryTwice(
                async () => await client.getBuffer(key),
                `Waited 5 sec to get redis key: ${key}, retrying once!`
            )
        })
    }

    public redisSet(
        key: string,
        value: unknown,
        tag: string,
        ttlSeconds?: number,
        options: CacheOptions = {}
    ): Promise<void> {
        const { jsonSerialize = true } = options

        return this.instrumentRedisQuery('query.redisSet', tag, { key }, async (client) => {
            const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
            if (ttlSeconds) {
                await client.set(key, serializedValue, 'EX', ttlSeconds)
            } else {
                await client.set(key, serializedValue)
            }
        })
    }

    public redisSetBuffer(key: string, value: Buffer, tag: string, ttlSeconds?: number): Promise<void> {
        return this.instrumentRedisQuery('query.redisSetBuffer', tag, { key }, async (client) => {
            if (ttlSeconds) {
                await client.setBuffer(key, value, 'EX', ttlSeconds)
            } else {
                await client.setBuffer(key, value)
            }
        })
    }

    public redisSetNX(
        key: string,
        value: unknown,
        tag: string,
        ttlSeconds?: number,
        options: CacheOptions = {}
    ): Promise<'OK' | null> {
        const { jsonSerialize = true } = options

        return this.instrumentRedisQuery('query.redisSetNX', tag, { key }, async (client) => {
            const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
            if (ttlSeconds) {
                return await client.set(key, serializedValue, 'EX', ttlSeconds, 'NX')
            } else {
                return await client.set(key, serializedValue, 'NX')
            }
        })
    }

    public redisSetMulti(kv: Array<[string, unknown]>, ttlSeconds?: number, options: CacheOptions = {}): Promise<void> {
        const { jsonSerialize = true } = options

        return this.instrumentRedisQuery('query.redisSet', undefined, { keys: kv.map((x) => x[0]) }, async (client) => {
            let pipeline = client.multi()
            for (const [key, value] of kv) {
                const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string)
                if (ttlSeconds) {
                    pipeline = pipeline.set(key, serializedValue, 'EX', ttlSeconds)
                } else {
                    pipeline = pipeline.set(key, serializedValue)
                }
            }
            await pipeline.exec()
        })
    }

    public redisIncr(key: string): Promise<number> {
        return this.instrumentRedisQuery('query.redisIncr', undefined, { key }, async (client) => {
            return await client.incr(key)
        })
    }

    public redisExpire(key: string, ttlSeconds: number): Promise<boolean> {
        return this.instrumentRedisQuery('query.redisExpire', undefined, { key }, async (client) => {
            return (await client.expire(key, ttlSeconds)) === 1
        })
    }

    public redisLPush(key: string, value: unknown, options: CacheOptions = {}): Promise<number> {
        const { jsonSerialize = true } = options

        return this.instrumentRedisQuery('query.redisLPush', undefined, { key }, async (client) => {
            const serializedValue = jsonSerialize ? JSON.stringify(value) : (value as string | string[])
            return await client.lpush(key, serializedValue)
        })
    }

    public redisLRange(key: string, startIndex: number, endIndex: number, tag?: string): Promise<string[]> {
        return this.instrumentRedisQuery('query.redisLRange', tag, { key, startIndex, endIndex }, async (client) => {
            return await client.lrange(key, startIndex, endIndex)
        })
    }

    public redisLLen(key: string): Promise<number> {
        return this.instrumentRedisQuery('query.redisLLen', undefined, { key }, async (client) => {
            return await client.llen(key)
        })
    }

    public redisBRPop(key1: string, key2: string): Promise<[string, string]> {
        return this.instrumentRedisQuery('query.redisBRPop', undefined, { key1, key2 }, async (client) => {
            return await client.brpop(key1, key2)
        })
    }

    public redisLRem(key: string, count: number, elementKey: string): Promise<number> {
        return this.instrumentRedisQuery(
            'query.redisLRem',
            undefined,
            {
                key,
                count,
                elementKey,
            },
            async (client) => {
                return await client.lrem(key, count, elementKey)
            }
        )
    }

    public redisLPop(key: string, count: number): Promise<string[]> {
        return this.instrumentRedisQuery(
            'query.redisLPop',
            undefined,
            {
                key,
                count,
            },
            async (client) => {
                return await client.lpop(key, count)
            }
        )
    }

    public redisSAddAndSCard(key: string, value: Redis.ValueType, ttlSeconds?: number): Promise<number> {
        return this.instrumentRedisQuery('query.redisSAddAndSCard', undefined, { key }, async (client) => {
            const multi = client.multi()
            multi.sadd(key, value)
            if (ttlSeconds) {
                multi.expire(key, ttlSeconds)
            }
            multi.scard(key)
            const results = await multi.exec()
            const scardResult = ttlSeconds ? results[2] : results[1]
            return scardResult[1]
        })
    }

    public redisSCard(key: string): Promise<number> {
        return this.instrumentRedisQuery(
            'query.redisSCard',
            undefined,
            {
                key,
            },
            async (client) => {
                return await client.scard(key)
            }
        )
    }

    public redisPublish(channel: string, message: string): Promise<number> {
        return this.instrumentRedisQuery(
            'query.redisPublish',
            undefined,
            {
                channel,
                message,
            },
            async (client) => {
                return await client.publish(channel, message)
            }
        )
    }

    private toPerson(row: RawPerson): InternalPerson {
        return {
            ...row,
            id: String(row.id),
            created_at: DateTime.fromISO(row.created_at).toUTC(),
            version: Number(row.version || 0),
        }
    }

    public async fetchPersons(database?: Database.Postgres, teamId?: number): Promise<InternalPerson[]>
    public async fetchPersons(database: Database.ClickHouse, teamId?: number): Promise<ClickHousePerson[]>
    public async fetchPersons(
        database: Database = Database.Postgres,
        teamId?: number
    ): Promise<InternalPerson[] | ClickHousePerson[]> {
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
                ${teamId ? `WHERE team_id = ${teamId}` : ''}
                GROUP BY team_id, id
                HAVING max(is_deleted)=0
            )
            `
            return (await this.clickhouseQuery(query)).data.map((row) => {
                const { 'person_max._timestamp': _discard1, 'person_max.id': _discard2, ...rest } = row
                return rest
            }) as ClickHousePerson[]
        } else if (database === Database.Postgres) {
            return await this.postgres
                .query<RawPerson>(PostgresUse.PERSONS_WRITE, 'SELECT * FROM posthog_person', undefined, 'fetchPersons')
                .then(({ rows }) => rows.map(this.toPerson))
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
    }

    // PersonDistinctId
    // testutil
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
                await this.clickhouseQuery(
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
            const result = await this.postgres.query(
                PostgresUse.PERSONS_WRITE, // used in tests only
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

    // Cohort & CohortPeople
    // testutil
    public async createCohort(cohort: Partial<Cohort>): Promise<Cohort> {
        const insertResult = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_cohort (name, description, deleted, groups, team_id,
                                         created_at, created_by_id, is_calculating,
                                         last_calculation, errors_calculating, is_static,
                                         version, pending_version)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
             RETURNING *;`,
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
                cohort.version,
                cohort.pending_version ?? cohort.version ?? 0,
            ],
            'createCohort'
        )
        return insertResult.rows[0]
    }

    public async addPersonToCohort(
        cohortId: number,
        personId: InternalPerson['id'],
        version: number | null
    ): Promise<CohortPeople> {
        const insertResult = await this.postgres.query(
            PostgresUse.PERSONS_WRITE,
            `INSERT INTO posthog_cohortpeople (cohort_id, person_id, version) VALUES ($1, $2, $3) RETURNING *;`,
            [cohortId, personId, version],
            'addPersonToCohort'
        )
        return insertResult.rows[0]
    }

    // Event (NOTE: not a Django model, stored in ClickHouse table `events`)

    public async fetchEvents(): Promise<ClickHouseEvent[]> {
        const queryResult = await this.clickhouseQuery<RawClickHouseEvent>(
            `SELECT * FROM events ORDER BY timestamp ASC`
        )
        return queryResult.data.map(parseRawClickHouseEvent)
    }

    public async fetchDeadLetterQueueEvents(): Promise<DeadLetterQueueEvent[]> {
        const result = await this.clickhouseQuery(`SELECT * FROM events_dead_letter_queue ORDER BY _timestamp ASC`)
        const events = result.data as DeadLetterQueueEvent[]
        return events
    }

    // SessionRecordingEvent

    public async fetchSessionRecordingEvents(): Promise<RawSessionRecordingEvent[]> {
        const events = (
            await this.clickhouseQuery<RawSessionRecordingEvent>(`SELECT * FROM session_recording_events`)
        ).data.map((event) => {
            return {
                ...event,
                snapshot_data: event.snapshot_data ? parseJSON(event.snapshot_data) : null,
            }
        })
        return events
    }

    // PluginLogEntry (NOTE: not a Django model, stored in ClickHouse table `plugin_log_entries`)

    public async fetchPluginLogEntries(): Promise<PluginLogEntry[]> {
        const queryResult = await this.clickhouseQuery(`SELECT * FROM plugin_log_entries`)
        return queryResult.data as PluginLogEntry[]
    }

    public queuePluginLogEntry(entry: LogEntryPayload): Promise<void> {
        const { pluginConfig, source, message, type, timestamp, instanceId } = entry
        const configuredLogLevel = pluginConfig.plugin?.log_level || this.pluginsDefaultLogLevel

        if (!shouldStoreLog(configuredLogLevel, type)) {
            return Promise.resolve()
        }

        const parsedEntry = {
            source,
            type,
            id: new UUIDT().toString(),
            team_id: pluginConfig.team_id,
            plugin_id: pluginConfig.plugin_id,
            plugin_config_id: pluginConfig.id,
            timestamp: (timestamp || new Date().toISOString()).replace('T', ' ').replace('Z', ''),
            message: safeClickhouseString(message),
            instance_id: instanceId.toString(),
        }

        if (parsedEntry.message.length > 50_000) {
            const { message, ...rest } = parsedEntry
            logger.warn('⚠️', 'Plugin log entry too long, ignoring.', rest)
            return Promise.resolve()
        }

        pluginLogEntryCounter.labels({ plugin_id: String(pluginConfig.plugin_id), source }).inc()

        try {
            // For logs, we relax our durability requirements a little and
            // do not wait for acks that Kafka has persisted the message to
            // disk.
            void this.kafkaProducer
                .queueMessages({
                    topic: KAFKA_PLUGIN_LOG_ENTRIES,
                    messages: [{ key: parsedEntry.id, value: JSON.stringify(parsedEntry) }],
                })
                .catch((error) => {
                    logger.warn('⚠️', 'Failed to produce plugin log entry', {
                        error,
                        entry: parsedEntry,
                    })
                })

            // TRICKY: We don't want to block the caller, so we return a promise that resolves immediately.
            return Promise.resolve()
        } catch (e) {
            captureException(e, { tags: { team_id: entry.pluginConfig.team_id } })
            console.error('Failed to produce message', e, parsedEntry)
            return Promise.resolve()
        }
    }

    // Action & ActionStep & Action<>Event

    public async fetchAllActionsGroupedByTeam(): Promise<Record<Team['id'], Record<Action['id'], Action>>> {
        return fetchAllActionsGroupedByTeam(this.postgres)
    }

    public async fetchAction(id: Action['id']): Promise<Action | null> {
        return await fetchAction(this.postgres, id)
    }

    // Hook (EE)

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
        organizationMembershipLevel = OrganizationMembershipLevel.Member,
    }: CreateUserPayload): Promise<QueryResult> {
        const createUserResult = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_user (uuid, password, first_name, last_name, email, distinct_id, is_staff, is_active, date_joined, events_column_config, current_organization_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
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
                organization_id,
            ],
            'createUser'
        )

        if (organization_id) {
            const now = new Date().toISOString()
            await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_organizationmembership (id, organization_id, user_id, level, joined_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)`,
                [
                    new UUIDT().toString(),
                    organization_id,
                    createUserResult.rows[0].id,
                    organizationMembershipLevel,
                    now,
                    now,
                ],
                'createOrganizationMembership'
            )
        }

        return createUserResult
    }

    public async createPersonalApiKey({
        id,
        user_id,
        label,
        secure_value,
        created_at,
    }: CreatePersonalApiKeyPayload): Promise<QueryResult> {
        return await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_personalapikey (id, user_id, label, secure_value, created_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING secure_value`,
            [id, user_id, label, secure_value, created_at.toISOString()],
            'createPersonalApiKey'
        )
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

        const selectResult: QueryResult = await this.postgres.query(
            tx ?? PostgresUse.PERSONS_WRITE,
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

    public async insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tx?: TransactionClient
    ): Promise<number> {
        const result = await this.postgres.query<{ version: string }>(
            tx ?? PostgresUse.PERSONS_WRITE,
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
                1,
            ],
            'upsertGroup'
        )

        if (result.rows.length === 0) {
            throw new RaceConditionError('Parallel posthog_group inserts, retry')
        }

        return Number(result.rows[0].version || 0)
    }

    public async updateGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        tag: string,
        tx?: TransactionClient
    ): Promise<number | undefined> {
        const result = await this.postgres.query<{ version: string }>(
            tx ?? PostgresUse.PERSONS_WRITE,
            `
            UPDATE posthog_group SET
            created_at = $4,
            group_properties = $5,
            properties_last_updated_at = $6,
            properties_last_operation = $7,
            version = COALESCE(version, 0)::numeric + 1
            WHERE team_id = $1 AND group_key = $2 AND group_type_index = $3
            RETURNING version
            `,
            [
                teamId,
                groupKey,
                groupTypeIndex,
                createdAt.toISO(),
                JSON.stringify(groupProperties),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
            ],
            tag
        )

        if (result.rows.length === 0) {
            return undefined
        }

        return Number(result.rows[0].version || 0)
    }

    public async updateGroupOptimistically(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        expectedVersion: number,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation
    ): Promise<number | undefined> {
        const result = await this.postgres.query<{ version: string }>(
            PostgresUse.PERSONS_WRITE,
            `
            UPDATE posthog_group SET
            created_at = $5,
            group_properties = $6,
            properties_last_updated_at = $7,
            properties_last_operation = $8,
            version = COALESCE(version, 0)::numeric + 1
            WHERE team_id = $1 AND group_key = $2 AND group_type_index = $3 AND version = $4
            RETURNING version
            `,
            [
                teamId,
                groupKey,
                groupTypeIndex,
                expectedVersion,
                createdAt.toISO(),
                JSON.stringify(groupProperties),
                JSON.stringify(propertiesLastUpdatedAt),
                JSON.stringify(propertiesLastOperation),
            ],
            'updateGroupOptimistically'
        )

        if (result.rows.length === 0) {
            return undefined
        }

        return Number(result.rows[0].version || 0)
    }

    public async upsertGroupClickhouse(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        version: number
    ): Promise<void> {
        await this.kafkaProducer.queueMessages({
            topic: KAFKA_GROUPS,
            messages: [
                {
                    value: JSON.stringify({
                        group_type_index: groupTypeIndex,
                        group_key: groupKey,
                        team_id: teamId,
                        group_properties: JSON.stringify(properties),
                        created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouseSecondPrecision),
                        version,
                    }),
                },
            ],
        })
    }

    // Used in tests
    public async fetchClickhouseGroups(): Promise<ClickhouseGroup[]> {
        const query = `
        SELECT group_type_index, group_key, created_at, team_id, group_properties FROM groups FINAL
        `
        return (await this.clickhouseQuery(query)).data as ClickhouseGroup[]
    }

    public async getTeamsInOrganizationsWithRootPluginAccess(): Promise<Team[]> {
        const selectResult = await this.postgres.query<Team>(
            PostgresUse.COMMON_READ,
            'SELECT * from posthog_team WHERE organization_id = (SELECT id from posthog_organization WHERE plugins_access_level = $1)',
            [OrganizationPluginsAccessLevel.ROOT],
            'getTeamsInOrganizationsWithRootPluginAccess'
        )
        for (const row of selectResult.rows) {
            // pg returns int8 as a string, since it can be larger than JS's max safe integer,
            // but this is not a problem for project_id, which is a long long way from that limit.
            row.project_id = Number(row.project_id) as ProjectId
        }
        return selectResult.rows
    }

    public async getPluginSource(pluginId: Plugin['id'], filename: string): Promise<string | null> {
        const { rows }: { rows: { source: string }[] } = await this.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT source FROM posthog_pluginsourcefile WHERE plugin_id = $1 AND filename = $2`,
            [pluginId, filename],
            'getPluginSource'
        )
        return rows[0]?.source ?? null
    }
}
