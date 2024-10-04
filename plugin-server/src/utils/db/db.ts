import ClickHouse from '@posthog/clickhouse'
import { CacheOptions, Properties } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'
import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'
import { QueryResult } from 'pg'

import { KAFKA_GROUPS, KAFKA_PERSON_DISTINCT_ID, KAFKA_PLUGIN_LOG_ENTRIES } from '../../config/kafka-topics'
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
    EventDefinitionType,
    EventPropertyType,
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
    PropertiesLastOperation,
    PropertiesLastUpdatedAt,
    PropertyDefinitionType,
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
import { fetchOrganization } from '../../worker/ingestion/organization-manager'
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
import { KafkaProducerWrapper } from './kafka-producer-wrapper'
import { personUpdateVersionMismatchCounter, pluginLogEntryCounter } from './metrics'
import { PostgresRouter, PostgresUse, TransactionClient } from './postgres'
import {
    generateKafkaPersonUpdateMessage,
    safeClickhouseString,
    sanitizeJsonbValue,
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

    public redisGet<T = unknown>(
        key: string,
        defaultValue: T,
        tag: string,
        options: CacheOptions = {}
    ): Promise<T | null> {
        const { jsonSerialize = true } = options

        return instrumentQuery('query.redisGet', tag, async () => {
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

    public redisSet(
        key: string,
        value: unknown,
        tag: string,
        ttlSeconds?: number,
        options: CacheOptions = {}
    ): Promise<void> {
        const { jsonSerialize = true } = options

        return instrumentQuery('query.redisSet', tag, async () => {
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

        return instrumentQuery('query.redisSet', undefined, async () => {
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
        return instrumentQuery('query.redisIncr', undefined, async () => {
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
        return instrumentQuery('query.redisExpire', undefined, async () => {
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

        return instrumentQuery('query.redisLPush', undefined, async () => {
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
        return instrumentQuery('query.redisLRange', undefined, async () => {
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
        return instrumentQuery('query.redisLLen', undefined, async () => {
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
        return instrumentQuery('query.redisBRPop', undefined, async () => {
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
        return instrumentQuery('query.redisLRem', undefined, async () => {
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
        return instrumentQuery('query.redisLPop', undefined, async () => {
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
        return instrumentQuery('query.redisPublish', undefined, async () => {
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

    private toPerson(row: RawPerson): InternalPerson {
        return {
            ...row,
            created_at: DateTime.fromISO(row.created_at).toUTC(),
            version: Number(row.version || 0),
        }
    }

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
            return (await this.clickhouseQuery(query)).data.map((row) => {
                const { 'person_max._timestamp': _discard1, 'person_max.id': _discard2, ...rest } = row
                return rest
            }) as ClickHousePerson[]
        } else if (database === Database.Postgres) {
            return await this.postgres
                .query<RawPerson>(PostgresUse.COMMON_WRITE, 'SELECT * FROM posthog_person', undefined, 'fetchPersons')
                .then(({ rows }) => rows.map(this.toPerson))
        } else {
            throw new Error(`Can't fetch persons for database: ${database}`)
        }
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

        await this.kafkaProducer.queueMessages({ kafkaMessages, waitForAck: true })
        return person
    }

    // Currently in use, but there are various problems with this function
    public async updatePersonDeprecated(
        person: InternalPerson,
        update: Partial<InternalPerson>,
        tx?: TransactionClient
    ): Promise<[InternalPerson, ProducerRecord[]]> {
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

    public async deletePerson(person: InternalPerson, tx?: TransactionClient): Promise<ProducerRecord[]> {
        const { rows } = await this.postgres.query<{ version: string }>(
            tx ?? PostgresUse.COMMON_WRITE,
            'DELETE FROM posthog_person WHERE team_id = $1 AND id = $2 RETURNING version',
            [person.team_id, person.id],
            'deletePerson'
        )

        let kafkaMessages: ProducerRecord[] = []

        if (rows.length > 0) {
            const [row] = rows
            kafkaMessages = [generateKafkaPersonUpdateMessage({ ...person, version: Number(row.version || 0) }, true)]
        }
        return kafkaMessages
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
            await this.kafkaProducer.queueMessages({ kafkaMessages, waitForAck: true })
        }
    }

    public async addDistinctIdPooled(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: TransactionClient
    ): Promise<ProducerRecord[]> {
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
    ): Promise<ProducerRecord[]> {
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
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_cohortpeople (cohort_id, person_id, version) VALUES ($1, $2, $3) RETURNING *;`,
            [cohortId, personId, version],
            'addPersonToCohort'
        )
        return insertResult.rows[0]
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
        const configuredLogLevel = pluginConfig.plugin?.log_level || this.pluginsDefaultLogLevel

        if (!shouldStoreLog(configuredLogLevel, type)) {
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
            return
        }

        pluginLogEntryCounter.labels({ plugin_id: String(pluginConfig.plugin_id), source }).inc()

        try {
            await this.kafkaProducer.queueSingleJsonMessage({
                topic: KAFKA_PLUGIN_LOG_ENTRIES,
                key: parsedEntry.id,
                object: parsedEntry,
                // For logs, we relax our durability requirements a little and
                // do not wait for acks that Kafka has persisted the message to
                // disk.
                waitForAck: false,
            })
        } catch (e) {
            captureException(e, { tags: { team_id: entry.pluginConfig.team_id } })
            console.error('Failed to produce message', e, parsedEntry)
        }
    }

    // EventDefinition

    public async fetchEventDefinitions(teamId?: number): Promise<EventDefinitionType[]> {
        return (
            await this.postgres.query(
                PostgresUse.COMMON_READ,
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
            await this.postgres.query(
                PostgresUse.COMMON_READ,
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
            await this.postgres.query(
                PostgresUse.COMMON_READ,
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
        return fetchAllActionsGroupedByTeam(this.postgres)
    }

    public async fetchAction(id: Action['id']): Promise<Action | null> {
        return await fetchAction(this.postgres, id)
    }

    // Organization

    public async fetchOrganization(organizationId: string): Promise<RawOrganization | undefined> {
        return await fetchOrganization(this.postgres, organizationId)
    }

    // Team

    public async fetchTeam(teamId: Team['id']): Promise<Team | null> {
        return await fetchTeam(this.postgres, teamId)
    }

    public async fetchTeamByToken(token: string): Promise<Team | null> {
        return await fetchTeamByToken(this.postgres, token)
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

    public async insertGroup(
        teamId: TeamId,
        groupTypeIndex: GroupTypeIndex,
        groupKey: string,
        groupProperties: Properties,
        createdAt: DateTime,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        version: number,
        tx?: TransactionClient
    ): Promise<void> {
        const result = await this.postgres.query(
            tx ?? PostgresUse.COMMON_WRITE,
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
            'upsertGroup'
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
        tx?: TransactionClient
    ): Promise<void> {
        await this.postgres.query(
            tx ?? PostgresUse.COMMON_WRITE,
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
            'upsertGroup'
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
        await this.kafkaProducer.queueMessage({
            kafkaMessage: {
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
            },
            waitForAck: true,
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
            await this.postgres.query(
                PostgresUse.COMMON_READ,
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
        await this.postgres.transaction(PostgresUse.COMMON_WRITE, 'addOrUpdatePublicJob', async (tx) => {
            let publicJobs: Record<string, any> = (
                await this.postgres.query(
                    tx,
                    'SELECT public_jobs FROM posthog_plugin WHERE id = $1 FOR UPDATE',
                    [pluginId],
                    'selectPluginPublicJobsForUpdate'
                )
            ).rows[0]?.public_jobs

            if (
                !publicJobs ||
                !(jobName in publicJobs) ||
                JSON.stringify(publicJobs[jobName]) !== JSON.stringify(jobPayloadJson)
            ) {
                publicJobs = { ...publicJobs, [jobName]: jobPayloadJson }

                await this.postgres.query(
                    tx,
                    'UPDATE posthog_plugin SET public_jobs = $1 WHERE id = $2',
                    [JSON.stringify(publicJobs), pluginId],
                    'updatePublicJob'
                )
            }
        })
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
