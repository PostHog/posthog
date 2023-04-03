import ClickHouse from '@posthog/clickhouse'
import { CacheOptions, Properties } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'
import { Pool as GenericPool } from 'generic-pool'
import { StatsD } from 'hot-shots'
import Redis from 'ioredis'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import { CELERY_DEFAULT_QUEUE } from '../../config/constants'
import { KAFKA_GROUPS, KAFKA_PERSON_DISTINCT_ID, KAFKA_PLUGIN_LOG_ENTRIES } from '../../config/kafka-topics'
import {
    Action,
    ActionStep,
    ClickHouseEvent,
    ClickhouseGroup,
    ClickHousePerson,
    ClickHousePersonDistinctId2,
    ClickHouseTimestamp,
    Cohort,
    CohortPeople,
    Database,
    DeadLetterQueueEvent,
    EventDefinitionType,
    EventPropertyType,
    Group,
    GroupKey,
    GroupTypeIndex,
    GroupTypeToColumnIndex,
    Hook,
    IngestionPersonData,
    OrganizationMembershipLevel,
    Person,
    PersonDistinctId,
    Plugin,
    PluginConfig,
    PluginLogEntry,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginLogLevel,
    PluginSourceFileStatus,
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    PropertyDefinitionType,
    RawAction,
    RawClickHouseEvent,
    RawGroup,
    RawOrganization,
    RawPerson,
    RawSessionRecordingEvent,
    Team,
    TeamId,
    TimestampFormat,
} from '../../types'
import { fetchTeam, fetchTeamByToken } from '../../worker/ingestion/team-manager'
import { parseRawClickHouseEvent } from '../event'
import { instrumentQuery } from '../metrics'
import { status } from '../status'
import {
    castTimestampOrNow,
    escapeClickHouseString,
    NoRowsUpdatedError,
    RaceConditionError,
    sanitizeSqlIdentifier,
    tryTwice,
    UUID,
    UUIDT,
} from '../utils'
import { OrganizationPluginsAccessLevel } from './../../types'
import { PromiseManager } from './../../worker/vm/promise-manager'
import { DependencyUnavailableError } from './error'
import { KafkaProducerWrapper } from './kafka-producer-wrapper'
import { postgresQuery } from './postgres'
import {
    generateKafkaPersonUpdateMessage,
    safeClickhouseString,
    shouldStoreLog,
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
]

/** The recommended way of accessing the database. */
export class DB {
    /** Postgres connection pool for primary database access. */
    postgres: Pool
    /** Redis used for various caches. */
    redisPool: GenericPool<Redis.Redis>

    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    kafkaProducer: KafkaProducerWrapper
    /** ClickHouse used for syncing Postgres and ClickHouse person data. */
    clickhouse: ClickHouse

    /** StatsD instance used to do instrumentation */
    statsd: StatsD | undefined

    /** How many unique group types to allow per team */
    MAX_GROUP_TYPES_PER_TEAM = 5

    /** Whether to write to clickhouse_person_unique_id topic */
    writeToPersonUniqueId?: boolean

    /** How many seconds to keep person info in Redis cache */
    PERSONS_AND_GROUPS_CACHE_TTL: number

    /** PromiseManager instance to keep track of voided promises */
    promiseManager: PromiseManager

    constructor(
        postgres: Pool,
        redisPool: GenericPool<Redis.Redis>,
        kafkaProducer: KafkaProducerWrapper,
        clickhouse: ClickHouse,
        statsd: StatsD | undefined,
        promiseManager: PromiseManager,
        personAndGroupsCacheTtl = 1
    ) {
        this.postgres = postgres
        this.redisPool = redisPool
        this.kafkaProducer = kafkaProducer
        this.clickhouse = clickhouse
        this.statsd = statsd
        this.PERSONS_AND_GROUPS_CACHE_TTL = personAndGroupsCacheTtl
        this.promiseManager = promiseManager
    }

    // Postgres

    public postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
        queryString: string | QueryConfig<I>,
        values: I | undefined,
        tag: string,
        client?: PoolClient
    ): Promise<QueryResult<R>> {
        return postgresQuery(client ?? this.postgres, queryString, values, tag, this.statsd)
    }

    public postgresTransaction<ReturnType>(
        tag: string,
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

                // if Postgres is down the ROLLBACK above won't work, but the transaction shouldn't be committed either
                if (e.message && POSTGRES_UNAVAILABLE_ERROR_MESSAGES.some((message) => e.message.includes(message))) {
                    throw new DependencyUnavailableError(e.message, 'Postgres', e)
                }

                throw e
            } finally {
                client.release()
                clearTimeout(timeout)
            }
        })
    }

    public async postgresBulkInsert<T extends Array<any>>(
        // Should have {VALUES} as a placeholder
        queryWithPlaceholder: string,
        values: Array<T>,
        tag: string,
        client?: PoolClient
    ): Promise<void> {
        if (values.length === 0) {
            return
        }

        const valuesWithPlaceholders = values
            .map((array, index) => {
                const len = array.length
                const valuesWithIndexes = array.map((_, subIndex) => `$${index * len + subIndex + 1}`)
                return `(${valuesWithIndexes.join(', ')})`
            })
            .join(', ')

        await this.postgresQuery(
            queryWithPlaceholder.replace('{VALUES}', valuesWithPlaceholders),
            values.flat(),
            tag,
            client
        )
    }

    // ClickHouse

    public clickhouseQuery<R extends Record<string, any> = Record<string, any>>(
        query: string,
        options?: ClickHouse.QueryOptions
    ): Promise<ClickHouse.ObjectQueryResult<R>> {
        return instrumentQuery(this.statsd, 'query.clickhouse', undefined, async () => {
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

    public redisGet<T = unknown>(key: string, defaultValue: T, options: CacheOptions = {}): Promise<T | null> {
        const { jsonSerialize = true } = options

        return instrumentQuery(this.statsd, 'query.regisGet', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('Getting redis key delayed. Waiting over 30 sec to get key.', { key })
            try {
                const value = await tryTwice(
                    async () => await client.get(key),
                    `Waited 5 sec to get redis key: ${key}, retrying once!`
                )
                if (typeof value === 'undefined' || value === null) {
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

    public redisSetMulti(kv: Array<[string, unknown]>, ttlSeconds?: number, options: CacheOptions = {}): Promise<void> {
        const { jsonSerialize = true } = options

        return instrumentQuery(this.statsd, 'query.redisSet', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('Setting redis key delayed. Waiting over 30 sec to set keys', {
                keys: kv.map((x) => x[0]),
            })
            try {
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

    public redisPublish(channel: string, message: string): Promise<number> {
        return instrumentQuery(this.statsd, 'query.redisPublish', undefined, async () => {
            const client = await this.redisPool.acquire()
            const timeout = timeoutGuard('Publish delayed. Waiting over 30 sec to perform Publish', {
                channel,
                message,
            })
            try {
                return await client.publish(channel, message)
            } finally {
                clearTimeout(timeout)
                await this.redisPool.release(client)
            }
        })
    }

    /** Calls Celery task. Works similarly to Task.apply_async in Python. */
    async celeryApplyAsync(taskName: string, args: any[] = [], kwargs: Record<string, any> = {}): Promise<void> {
        const taskId = new UUIDT().toString()
        const deliveryTag = new UUIDT().toString()
        const body = [args, kwargs, { callbacks: null, errbacks: null, chain: null, chord: null }]
        /** A base64-encoded JSON representation of the body tuple. */
        const bodySerialized = Buffer.from(JSON.stringify(body)).toString('base64')
        await this.redisLPush(CELERY_DEFAULT_QUEUE, {
            body: bodySerialized,
            'content-encoding': 'utf-8',
            'content-type': 'application/json',
            headers: {
                lang: 'js',
                task: taskName,
                id: taskId,
                retries: 0,
                root_id: taskId,
                parent_id: null,
                group: null,
            },
            properties: {
                correlation_id: taskId,
                delivery_mode: 2,
                delivery_tag: deliveryTag,
                delivery_info: { exchange: '', routing_key: CELERY_DEFAULT_QUEUE },
                priority: 0,
                body_encoding: 'base64',
            },
        })
    }

    REDIS_PERSON_ID_PREFIX = 'person_id'
    REDIS_PERSON_UUID_PREFIX = 'person_uuid'
    REDIS_PERSON_CREATED_AT_PREFIX = 'person_created_at'
    REDIS_PERSON_PROPERTIES_PREFIX = 'person_props'
    REDIS_GROUP_DATA_PREFIX = 'group_data_cache_v2'

    private getPersonIdCacheKey(teamId: number, distinctId: string): string {
        return `${this.REDIS_PERSON_ID_PREFIX}:${teamId}:${distinctId}`
    }

    private getPersonUuidCacheKey(teamId: number, personId: number): string {
        return `${this.REDIS_PERSON_UUID_PREFIX}:${teamId}:${personId}`
    }

    private getPersonCreatedAtCacheKey(teamId: number, personId: number): string {
        return `${this.REDIS_PERSON_CREATED_AT_PREFIX}:${teamId}:${personId}`
    }

    private getPersonPropertiesCacheKey(teamId: number, personId: number): string {
        return `${this.REDIS_PERSON_PROPERTIES_PREFIX}:${teamId}:${personId}`
    }

    public getGroupDataCacheKey(teamId: number, groupTypeIndex: number, groupKey: string): string {
        return `${this.REDIS_GROUP_DATA_PREFIX}:${teamId}:${groupTypeIndex}:${groupKey}`
    }

    private async updatePersonIdCache(teamId: number, distinctId: string, personId: number): Promise<void> {
        await this.redisSet(this.getPersonIdCacheKey(teamId, distinctId), personId, this.PERSONS_AND_GROUPS_CACHE_TTL)
    }

    private async updatePersonUuidCache(teamId: number, personId: number, uuid: string): Promise<void> {
        await this.redisSet(this.getPersonUuidCacheKey(teamId, personId), uuid, this.PERSONS_AND_GROUPS_CACHE_TTL)
    }

    private async updatePersonCreatedAtIsoCache(teamId: number, personId: number, createdAtIso: string): Promise<void> {
        await this.redisSet(
            this.getPersonCreatedAtCacheKey(teamId, personId),
            createdAtIso,
            this.PERSONS_AND_GROUPS_CACHE_TTL
        )
    }

    private async updatePersonCreatedAtCache(teamId: number, personId: number, createdAt: DateTime): Promise<void> {
        await this.updatePersonCreatedAtIsoCache(teamId, personId, createdAt.toISO())
    }

    private async updatePersonPropertiesCache(teamId: number, personId: number, properties: Properties): Promise<void> {
        await this.redisSet(
            this.getPersonPropertiesCacheKey(teamId, personId),
            properties,
            this.PERSONS_AND_GROUPS_CACHE_TTL
        )
    }

    public async getPersonId(teamId: number, distinctId: string): Promise<number | null> {
        const personId = await this.redisGet(this.getPersonIdCacheKey(teamId, distinctId), null)
        if (personId) {
            this.statsd?.increment(`person_info_cache.hit`, { lookup: 'person_id', team_id: teamId.toString() })
            return Number(personId)
        }
        this.statsd?.increment(`person_info_cache.miss`, { lookup: 'person_id', team_id: teamId.toString() })
        // Query from postgres and update cache
        const result = await this.postgresQuery(
            'SELECT person_id FROM posthog_persondistinctid WHERE team_id=$1 AND distinct_id=$2 LIMIT 1',
            [teamId, distinctId],
            'fetchPersonId'
        )
        if (result.rows.length > 0) {
            const personId = Number(result.rows[0].person_id)
            await this.updatePersonIdCache(teamId, distinctId, personId)
            return personId
        }
        return null
    }

    public async getPersonDataByPersonId(teamId: number, personId: number): Promise<IngestionPersonData | undefined> {
        const [personUuid, personCreatedAtIso, personProperties] = await Promise.all([
            this.redisGet(this.getPersonUuidCacheKey(teamId, personId), null),
            this.redisGet(this.getPersonCreatedAtCacheKey(teamId, personId), null),
            this.redisGet(this.getPersonPropertiesCacheKey(teamId, personId), null),
        ])
        if (personUuid !== null && personCreatedAtIso !== null && personProperties !== null) {
            this.statsd?.increment(`person_info_cache.hit`, { lookup: 'person_properties', team_id: teamId.toString() })

            return {
                team_id: teamId,
                uuid: String(personUuid),
                created_at: DateTime.fromISO(String(personCreatedAtIso)).toUTC(),
                properties: personProperties as Properties, // redisGet does JSON.parse and we redisSet JSON.stringify(Properties)
                id: personId,
            }
        }
        this.statsd?.increment(`person_info_cache.miss`, { lookup: 'person_properties', team_id: teamId.toString() })
        // Query from postgres and update cache
        const result = await this.postgresQuery(
            'SELECT uuid, created_at, properties FROM posthog_person WHERE team_id=$1 AND id=$2 LIMIT 1',
            [teamId, personId],
            'fetchPersonProperties'
        )
        if (result.rows.length !== 0) {
            const personUuid = String(result.rows[0].uuid)
            const personCreatedAtIso = String(result.rows[0].created_at)
            const personProperties: Properties = result.rows[0].properties
            this.promiseManager.trackPromise(this.updatePersonUuidCache(teamId, personId, personUuid))
            this.promiseManager.trackPromise(this.updatePersonCreatedAtIsoCache(teamId, personId, personCreatedAtIso))
            this.promiseManager.trackPromise(this.updatePersonPropertiesCache(teamId, personId, personProperties))
            return {
                team_id: teamId,
                uuid: personUuid,
                created_at: DateTime.fromISO(personCreatedAtIso).toUTC(),
                properties: personProperties,
                id: personId,
            }
        }
        return undefined
    }

    public async getPersonData(teamId: number, distinctId: string): Promise<IngestionPersonData | undefined> {
        const personId = await this.getPersonId(teamId, distinctId)
        if (personId) {
            return await this.getPersonDataByPersonId(teamId, personId)
        }
        return undefined
    }

    public async updateGroupCache(
        teamId: number,
        groupTypeIndex: number,
        groupKey: string,
        groupData: CachedGroupData
    ): Promise<void> {
        const groupCacheKey = this.getGroupDataCacheKey(teamId, groupTypeIndex, groupKey)
        await this.redisSet(groupCacheKey, groupData)
    }

    public async getGroupsColumns(
        teamId: number,
        groupIds: GroupId[]
    ): Promise<Record<string, string | ClickHouseTimestamp>> {
        const groupPropertiesColumns: Record<string, string> = {}
        const groupCreatedAtColumns: Record<string, ClickHouseTimestamp> = {}

        for (const [groupTypeIndex, groupKey] of groupIds) {
            const groupCacheKey = this.getGroupDataCacheKey(teamId, groupTypeIndex, groupKey)
            const propertiesColumnName = `group${groupTypeIndex}_properties`
            const createdAtColumnName = `group${groupTypeIndex}_created_at`

            // Lookup data from the cache, but don't throw errors - we'll fallback to Postgres if Redis is unavailable
            try {
                const cachedGroupData = await this.redisGet<CachedGroupData | null>(groupCacheKey, null)

                if (cachedGroupData) {
                    this.statsd?.increment('group_info_cache.hit')
                    groupPropertiesColumns[propertiesColumnName] = JSON.stringify(cachedGroupData.properties)
                    groupCreatedAtColumns[createdAtColumnName] = cachedGroupData.created_at

                    continue
                }
            } catch (error) {
                captureException(error)
            }

            this.statsd?.increment('group_info_cache.miss')

            // If we didn't find cached data, lookup the group from Postgres
            const storedGroupData = await this.fetchGroup(teamId, groupTypeIndex as GroupTypeIndex, groupKey)

            if (storedGroupData) {
                groupPropertiesColumns[propertiesColumnName] = JSON.stringify(storedGroupData.group_properties)

                const createdAt = castTimestampOrNow(
                    storedGroupData.created_at.toUTC(),
                    TimestampFormat.ClickHouse
                ) as ClickHouseTimestamp

                groupCreatedAtColumns[createdAtColumnName] = createdAt

                // We found data in Postgres, so update the cache
                // We also don't want to throw here, worst case is we'll have to fetch from Postgres again next time
                try {
                    await this.updateGroupCache(teamId, groupTypeIndex, groupKey, {
                        properties: storedGroupData.group_properties,
                        created_at: createdAt,
                    })
                } catch (error) {
                    captureException(error)
                }
            } else {
                // We couldn't find the data from the cache nor Postgres, so record this in a metric and in Sentry
                this.statsd?.increment('groups_data_missing_entirely')
                status.debug('🔍', `Could not find group data for group ${groupCacheKey} in cache or storage`)

                groupPropertiesColumns[propertiesColumnName] = '{}'
                groupCreatedAtColumns[createdAtColumnName] = castTimestampOrNow(
                    DateTime.fromJSDate(new Date(0)).toUTC(),
                    TimestampFormat.ClickHouse
                ) as ClickHouseTimestamp
            }
        }

        return {
            ...groupPropertiesColumns,
            ...groupCreatedAtColumns,
        }
    }

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

        const selectResult: QueryResult = await this.postgresQuery<RawPerson>(
            queryString,
            values,
            'fetchPerson',
            client
        )

        if (selectResult.rows.length > 0) {
            const rawPerson = selectResult.rows[0]
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

        const person = await this.postgresTransaction('createPerson', async (client) => {
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

            kafkaMessages.push(
                generateKafkaPersonUpdateMessage(createdAt, properties, teamId, isIdentified, uuid, person.version)
            )

            for (const distinctId of distinctIds || []) {
                const messages = await this.addDistinctIdPooled(person, distinctId, client)
                kafkaMessages.push(...messages)
            }

            return person
        })

        await this.kafkaProducer.queueMessages(kafkaMessages)

        // Update person info cache - we want to await to make sure the Event gets the right properties
        await Promise.all(
            (distinctIds || [])
                .map((distinctId) => this.updatePersonIdCache(teamId, distinctId, person.id))
                .concat([
                    this.updatePersonUuidCache(teamId, person.id, person.uuid),
                    this.updatePersonCreatedAtCache(teamId, person.id, person.created_at),
                    this.updatePersonPropertiesCache(teamId, person.id, properties),
                ])
        )

        return person
    }

    // Currently in use, but there are various problems with this function
    public async updatePersonDeprecated(
        person: Person,
        update: Partial<Person>,
        client?: PoolClient
    ): Promise<[Person, ProducerRecord[]]> {
        const updateValues = Object.values(unparsePersonPartial(update))

        // short circuit if there are no updates to be made
        if (updateValues.length === 0) {
            return [person, []]
        }

        const values = [...updateValues, person.id]

        // Potentially overriding values badly if there was an update to the person after computing updateValues above
        const queryString = `UPDATE posthog_person SET version = COALESCE(version, 0)::numeric + 1, ${Object.keys(
            update
        ).map((field, index) => `"${sanitizeSqlIdentifier(field)}" = $${index + 1}`)} WHERE id = $${
            Object.values(update).length + 1
        }
        RETURNING *`

        const updateResult: QueryResult = await this.postgresQuery(queryString, values, 'updatePerson', client)
        if (updateResult.rows.length == 0) {
            throw new NoRowsUpdatedError(
                `Person with team_id="${person.team_id}" and uuid="${person.uuid} couldn't be updated`
            )
        }
        const updatedPersonRaw = updateResult.rows[0] as RawPerson
        const updatedPerson = {
            ...updatedPersonRaw,
            created_at: DateTime.fromISO(updatedPersonRaw.created_at).toUTC(),
            version: Number(updatedPersonRaw.version || 0),
        } as Person

        // Track the disparity between the version on the database and the version of the person we have in memory
        // Without races, the returned person (updatedPerson) should have a version that's only +1 the person in memory
        const versionDisparity = updatedPerson.version - person.version - 1
        if (versionDisparity > 0) {
            this.statsd?.increment('person_update_version_mismatch', { versionDisparity: String(versionDisparity) })
        }

        const kafkaMessages = []
        const message = generateKafkaPersonUpdateMessage(
            updatedPerson.created_at,
            updatedPerson.properties,
            updatedPerson.team_id,
            updatedPerson.is_identified,
            updatedPerson.uuid,
            updatedPerson.version
        )
        if (client) {
            kafkaMessages.push(message)
        } else {
            await this.kafkaProducer.queueMessage(message)
        }

        // Update person info cache - we want to await to make sure the Event gets the right properties
        await this.updatePersonPropertiesCache(updatedPerson.team_id, updatedPerson.id, updatedPerson.properties)
        await this.updatePersonCreatedAtCache(updatedPerson.team_id, updatedPerson.id, updatedPerson.created_at)

        return [updatedPerson, kafkaMessages]
    }

    public async deletePerson(person: Person, client?: PoolClient): Promise<ProducerRecord[]> {
        const result = await this.postgresQuery<{ version: string }>(
            'DELETE FROM posthog_person WHERE team_id = $1 AND id = $2 RETURNING version',
            [person.team_id, person.id],
            'deletePerson',
            client
        )

        let kafkaMessages: ProducerRecord[] = []

        if (result.rows.length > 0) {
            kafkaMessages = [
                generateKafkaPersonUpdateMessage(
                    person.created_at,
                    person.properties,
                    person.team_id,
                    person.is_identified,
                    person.uuid,
                    Number(result.rows[0].version || 0) + 100, // keep in sync with delete_person in posthog/models/person/util.py
                    1
                ),
            ]
        }
        // TODO: remove from cache
        return kafkaMessages
    }

    // PersonDistinctId

    public async fetchDistinctIds(person: Person, database?: Database.Postgres): Promise<PersonDistinctId[]>
    public async fetchDistinctIds(person: Person, database: Database.ClickHouse): Promise<ClickHousePersonDistinctId2[]>
    public async fetchDistinctIds(
        person: Person,
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
        if (kafkaMessages.length) {
            await this.kafkaProducer.queueMessages(kafkaMessages)
        }
        // Update person info cache - we want to await to make sure the Event gets the right properties
        await this.updatePersonIdCache(person.team_id, distinctId, person.id)
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
        const version = Number(versionStr || 0)
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

            // Update person info cache - we want to await to make sure the Event gets the right properties
            await this.updatePersonIdCache(usefulColumns.team_id, usefulColumns.distinct_id, usefulColumns.person_id)
        }
        return kafkaMessages
    }

    // Cohort & CohortPeople
    // testutil
    public async createCohort(cohort: Partial<Cohort>): Promise<Cohort> {
        const insertResult = await this.postgresQuery(
            `INSERT INTO posthog_cohort (name, description, deleted, groups, team_id, created_at, created_by_id, is_calculating, last_calculation,errors_calculating, is_static, version, pending_version) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) RETURNING *;`,
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

    public async doesPersonBelongToCohort(cohortId: number, person: IngestionPersonData): Promise<boolean> {
        const psqlResult = await this.postgresQuery(
            `
            SELECT count(1) AS count
            FROM posthog_cohortpeople
            JOIN posthog_cohort ON (posthog_cohort.id = posthog_cohortpeople.cohort_id)
            WHERE cohort_id=$1
              AND person_id=$2
              AND posthog_cohortpeople.version IS NOT DISTINCT FROM posthog_cohort.version
            `,
            [cohortId, person.id],
            'doesPersonBelongToCohort'
        )
        return psqlResult.rows[0].count > 0
    }

    public async addPersonToCohort(
        cohortId: number,
        personId: Person['id'],
        version: number | null
    ): Promise<CohortPeople> {
        const insertResult = await this.postgresQuery(
            `INSERT INTO posthog_cohortpeople (cohort_id, person_id, version) VALUES ($1, $2, $3) RETURNING *;`,
            [cohortId, personId, version],
            'addPersonToCohort'
        )
        return insertResult.rows[0]
    }

    // Feature Flag Hash Key overrides
    public async addFeatureFlagHashKeysForMergedPerson(
        teamID: Team['id'],
        sourcePersonID: Person['id'],
        targetPersonID: Person['id']
    ): Promise<void> {
        // Delete and insert in a single query to ensure
        // this function is safe wherever it is run.
        // The CTE helps make this happen.
        //
        // Every override is unique for a team-personID-featureFlag combo.
        // In case we run into a conflict we would ideally use the override from most recent
        // personId used, so the user experience is consistent, however that's tricky to figure out
        // this also happens rarely, so we're just going to do the performance optimal thing
        // i.e. do nothing on conflicts, so we keep using the value that the person merged into had
        await this.postgresQuery(
            `
            WITH deletions AS (
                DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = $1 AND person_id = $2
                RETURNING team_id, person_id, feature_flag_key, hash_key
            )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, $3, feature_flag_key, hash_key
                FROM deletions
                ON CONFLICT DO NOTHING
            `,
            [teamID, sourcePersonID, targetPersonID],
            'addFeatureFlagHashKeysForMergedPerson'
        )
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
                snapshot_data: event.snapshot_data ? JSON.parse(event.snapshot_data) : null,
            }
        })
        return events
    }

    // PluginLogEntry (NOTE: not a Django model, stored in ClickHouse table `plugin_log_entries`)

    public async fetchPluginLogEntries(): Promise<PluginLogEntry[]> {
        const queryResult = await this.clickhouseQuery(`SELECT * FROM plugin_log_entries`)
        return queryResult.data as PluginLogEntry[]
    }

    public async queuePluginLogEntry(entry: LogEntryPayload): Promise<void> {
        const { pluginConfig, source, message, type, timestamp, instanceId } = entry

        const logLevel = pluginConfig.plugin?.log_level

        if (!shouldStoreLog(logLevel || PluginLogLevel.Full, source, type)) {
            return
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
            status.warn('⚠️', 'Plugin log entry too long, ignoring.', rest)
            this.statsd?.increment('logs.entries_too_large', {
                source,
                team_id: pluginConfig.team_id.toString(),
                plugin_id: pluginConfig.plugin_id.toString(),
            })
            return
        }

        this.statsd?.increment(`logs.entries_created`, {
            source,
            team_id: pluginConfig.team_id.toString(),
            plugin_id: pluginConfig.plugin_id.toString(),
        })
        this.statsd?.increment('logs.entries_size', {
            source,
            team_id: pluginConfig.team_id.toString(),
            plugin_id: pluginConfig.plugin_id.toString(),
        })

        try {
            await this.kafkaProducer.queueSingleJsonMessage(KAFKA_PLUGIN_LOG_ENTRIES, parsedEntry.id, parsedEntry)
        } catch (e) {
            captureException(e)
            console.error('Failed to produce message', e, parsedEntry)
        }
    }

    // EventDefinition

    public async fetchEventDefinitions(teamId?: number): Promise<EventDefinitionType[]> {
        return (
            await this.postgresQuery(
                `
                SELECT * FROM posthog_eventdefinition
                ${teamId ? 'WHERE team_id = $1' : ''}
                -- Order by something that gives a deterministic order. Note
                -- that this is a unique index.
                ORDER BY (team_id, name)
                `,
                teamId ? [teamId] : undefined,
                'fetchEventDefinitions'
            )
        ).rows as EventDefinitionType[]
    }

    // PropertyDefinition

    public async fetchPropertyDefinitions(teamId?: number): Promise<PropertyDefinitionType[]> {
        return (
            await this.postgresQuery(
                `
                SELECT * FROM posthog_propertydefinition
                ${teamId ? 'WHERE team_id = $1' : ''}
                -- Order by something that gives a deterministic order. Note
                -- that this is a unique index.
                ORDER BY (team_id, name, type, coalesce(group_type_index, -1))
                `,
                teamId ? [teamId] : undefined,
                'fetchPropertyDefinitions'
            )
        ).rows as PropertyDefinitionType[]
    }

    // EventProperty

    public async fetchEventProperties(teamId?: number): Promise<EventPropertyType[]> {
        return (
            await this.postgresQuery(
                `
                    SELECT * FROM posthog_eventproperty
                    ${teamId ? 'WHERE team_id = $1' : ''}
                    -- Order by something that gives a deterministic order. Note
                    -- that this is a unique index.
                    ORDER BY (team_id, event, property)
                `,
                teamId ? [teamId] : undefined,
                'fetchEventProperties'
            )
        ).rows as EventPropertyType[]
    }

    // Action & ActionStep & Action<>Event

    public async fetchAllActionsGroupedByTeam(): Promise<Record<Team['id'], Record<Action['id'], Action>>> {
        const restHooks = await this.fetchActionRestHooks()
        const restHookActionIds = restHooks.map(({ resource_id }) => resource_id)

        const rawActions = (
            await this.postgresQuery<RawAction>(
                `
                SELECT
                    id,
                    team_id,
                    name,
                    description,
                    created_at,
                    created_by_id,
                    deleted,
                    post_to_slack,
                    slack_message_format,
                    is_calculating,
                    updated_at,
                    last_calculated_at
                FROM posthog_action
                WHERE deleted = FALSE AND (post_to_slack OR id = ANY($1))
            `,
                [restHookActionIds],
                'fetchActions'
            )
        ).rows

        const pluginIds: number[] = rawActions.map(({ id }) => id)
        const actionSteps: (ActionStep & { team_id: Team['id'] })[] = (
            await this.postgresQuery(
                `
                    SELECT posthog_actionstep.*, posthog_action.team_id
                    FROM posthog_actionstep JOIN posthog_action ON (posthog_action.id = posthog_actionstep.action_id)
                    WHERE posthog_action.id = ANY($1)
                `,
                [pluginIds],
                'fetchActionSteps'
            )
        ).rows
        const actions: Record<Team['id'], Record<Action['id'], Action>> = {}
        for (const rawAction of rawActions) {
            if (!actions[rawAction.team_id]) {
                actions[rawAction.team_id] = {}
            }

            actions[rawAction.team_id][rawAction.id] = {
                ...rawAction,
                steps: [],
                hooks: [],
            }
        }
        for (const hook of restHooks) {
            if (hook.resource_id !== null && actions[hook.team_id]?.[hook.resource_id]) {
                actions[hook.team_id][hook.resource_id].hooks.push(hook)
            }
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

        const [steps, hooks] = await Promise.all([
            this.postgresQuery<ActionStep>(
                `SELECT * FROM posthog_actionstep WHERE action_id = $1`,
                [id],
                'fetchActionSteps'
            ),
            this.fetchActionRestHooks(id),
        ])

        const action: Action = { ...rawActions[0], steps: steps.rows, hooks }
        return action.post_to_slack || action.hooks.length > 0 ? action : null
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

    public async fetchTeam(teamId: Team['id']): Promise<Team | null> {
        return await fetchTeam(this.postgres, teamId)
    }

    public async fetchTeamByToken(token: string): Promise<Team | null> {
        return await fetchTeamByToken(this.postgres, token)
    }

    // Hook (EE)

    private async fetchActionRestHooks(actionId?: Hook['resource_id']): Promise<Hook[]> {
        try {
            const { rows } = await this.postgresQuery<Hook>(
                `
                SELECT *
                FROM ee_hook
                WHERE event = 'action_performed'
                ${actionId !== undefined ? 'AND resource_id = $1' : ''}
                `,
                actionId !== undefined ? [actionId] : [],
                'fetchActionRestHooks'
            )
            return rows
        } catch (err) {
            // On FOSS this table does not exist - ignore errors
            if (err.message.includes('relation "ee_hook" does not exist')) {
                return []
            }

            throw err
        }
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
        organizationMembershipLevel = OrganizationMembershipLevel.Member,
    }: CreateUserPayload): Promise<QueryResult> {
        const createUserResult = await this.postgresQuery(
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
            await this.postgresQuery(
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
        return await this.postgresQuery(
            `INSERT INTO posthog_personalapikey (id, user_id, label, secure_value, created_at)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING secure_value`,
            [id, user_id, label, secure_value, created_at.toISOString()],
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

    public async fetchInstanceSetting<Type>(key: string): Promise<Type | null> {
        const result = await this.postgresQuery<{ raw_value: string }>(
            `SELECT raw_value FROM posthog_instancesetting WHERE key = $1`,
            [key],
            'fetchInstanceSetting'
        )

        if (result.rows.length > 0) {
            const value = JSON.parse(result.rows[0].raw_value)
            return value
        } else {
            return null
        }
    }

    public async upsertInstanceSetting(key: string, value: string | number | boolean): Promise<void> {
        await this.postgresQuery(
            `
                INSERT INTO posthog_instancesetting (key, raw_value)
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET raw_value = EXCLUDED.raw_value
            `,
            [key, JSON.stringify(value)],
            'upsertInstanceSetting'
        )
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
        client?: PoolClient,
        options: { cache?: boolean } = { cache: true }
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

        if (options?.cache) {
            await this.updateGroupCache(teamId, groupTypeIndex, groupKey, {
                properties: groupProperties,
                created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouse),
            })
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

        await this.updateGroupCache(teamId, groupTypeIndex, groupKey, {
            properties: groupProperties,
            created_at: castTimestampOrNow(createdAt, TimestampFormat.ClickHouse),
        })
    }

    public async upsertGroupClickhouse(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        properties: Properties,
        createdAt: DateTime,
        version: number
    ): Promise<void> {
        await this.kafkaProducer.queueMessage({
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
        return (
            await this.postgresQuery(
                'SELECT * from posthog_team WHERE organization_id = (SELECT id from posthog_organization WHERE plugins_access_level = $1)',
                [OrganizationPluginsAccessLevel.ROOT],
                'getTeamsInOrganizationsWithRootPluginAccess'
            )
        ).rows as Team[]
    }

    public async addOrUpdatePublicJob(
        pluginId: number,
        jobName: string,
        jobPayloadJson: Record<string, any>
    ): Promise<void> {
        await this.postgresTransaction('addOrUpdatePublicJob', async (client) => {
            let publicJobs: Record<string, any> = (
                await this.postgresQuery(
                    'SELECT public_jobs FROM posthog_plugin WHERE id = $1 FOR UPDATE',
                    [pluginId],
                    'selectPluginPublicJobsForUpdate',
                    client
                )
            ).rows[0]?.public_jobs

            if (
                !publicJobs ||
                !(jobName in publicJobs) ||
                JSON.stringify(publicJobs[jobName]) !== JSON.stringify(jobPayloadJson)
            ) {
                publicJobs = { ...publicJobs, [jobName]: jobPayloadJson }

                await this.postgresQuery(
                    'UPDATE posthog_plugin SET public_jobs = $1 WHERE id = $2',
                    [JSON.stringify(publicJobs), pluginId],
                    'updatePublicJob',
                    client
                )
            }
        })
    }

    public async getPluginSource(pluginId: Plugin['id'], filename: string): Promise<string | null> {
        const { rows }: { rows: { source: string }[] } = await this.postgresQuery(
            `SELECT source FROM posthog_pluginsourcefile WHERE plugin_id = $1 AND filename = $2`,
            [pluginId, filename],
            'getPluginSource'
        )
        return rows[0]?.source ?? null
    }

    public async setPluginTranspiled(pluginId: Plugin['id'], filename: string, transpiled: string): Promise<void> {
        await this.postgresQuery(
            `INSERT INTO posthog_pluginsourcefile (id, plugin_id, filename, status, transpiled, updated_at) VALUES($1, $2, $3, $4, $5, NOW())
                ON CONFLICT ON CONSTRAINT unique_filename_for_plugin
                DO UPDATE SET status = $4, transpiled = $5, error = NULL, updated_at = NOW()`,
            [new UUIDT().toString(), pluginId, filename, PluginSourceFileStatus.Transpiled, transpiled],
            'setPluginTranspiled'
        )
    }

    public async setPluginTranspiledError(pluginId: Plugin['id'], filename: string, error: string): Promise<void> {
        await this.postgresQuery(
            `INSERT INTO posthog_pluginsourcefile (id, plugin_id, filename, status, error, updated_at) VALUES($1, $2, $3, $4, $5, NOW())
                ON CONFLICT ON CONSTRAINT unique_filename_for_plugin
                DO UPDATE SET status = $4, error = $5, transpiled = NULL, updated_at = NOW()`,
            [new UUIDT().toString(), pluginId, filename, PluginSourceFileStatus.Error, error],
            'setPluginTranspiledError'
        )
    }

    public async getPluginTranspilationLock(pluginId: Plugin['id'], filename: string): Promise<boolean> {
        const response = await this.postgresQuery(
            `INSERT INTO posthog_pluginsourcefile (id, plugin_id, filename, status, transpiled, updated_at) VALUES($1, $2, $3, $4, NULL, NOW())
                ON CONFLICT ON CONSTRAINT unique_filename_for_plugin
                DO UPDATE SET status = $4, updated_at = NOW() WHERE (posthog_pluginsourcefile.status IS NULL OR posthog_pluginsourcefile.status = $5) RETURNING status`,
            [new UUIDT().toString(), pluginId, filename, PluginSourceFileStatus.Locked, ''],
            'getPluginTranspilationLock'
        )
        return response.rowCount > 0
    }
}
