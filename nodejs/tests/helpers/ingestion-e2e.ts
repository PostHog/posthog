import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { v4 } from 'uuid'

import { IntegrationManagerService } from '../../src/cdp/services/managers/integration-manager.service'
import { EncryptedFields } from '../../src/cdp/utils/encryption-utils'
import { defaultConfig } from '../../src/config/config'
import { KAFKA_INGESTION_WARNINGS } from '../../src/config/kafka-topics'
import {
    createCookielessRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
} from '../../src/config/redis-pools'
import { CookielessManager } from '../../src/ingestion/cookieless/cookieless-manager'
import { buildGroupRepository, buildPersonRepository, createPersonHogClient } from '../../src/ingestion/personhog'
import { KafkaProducerWrapper } from '../../src/kafka/producer'
import { PipelineEvent, PluginsServerConfig, ProjectId, RawClickHouseEvent, RedisPool, Team } from '../../src/types'
import { PostgresRouter } from '../../src/utils/db/postgres'
import { createRedisPoolFromConfig } from '../../src/utils/db/redis'
import { parseRawClickHouseEvent } from '../../src/utils/event'
import { GeoIPService } from '../../src/utils/geoip'
import { parseJSON } from '../../src/utils/json-parse'
import { PubSub } from '../../src/utils/pubsub'
import { TeamManager } from '../../src/utils/team-manager'
import { UUIDT } from '../../src/utils/utils'
import { GroupTypeManager } from '../../src/worker/ingestion/group-type-manager'
import { GroupRepository } from '../../src/worker/ingestion/groups/repositories/group-repository.interface'
import { PostgresGroupRepository } from '../../src/worker/ingestion/groups/repositories/postgres-group-repository'
import { PersonRepository } from '../../src/worker/ingestion/persons/repositories/person-repository'
import { PostgresPersonRepository } from '../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { Clickhouse } from './clickhouse'
import { waitForExpect } from './expectations'
import { createUserTeamAndOrganization } from './sql'

export const DEFAULT_TEAM: Team = {
    id: 2,
    project_id: 2 as ProjectId,
    organization_id: '2',
    uuid: v4(),
    name: '2',
    anonymize_ips: true,
    api_token: 'api_token',
    secret_api_token: null,
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
    extra_settings: null,
}

export class EventBuilder {
    private event: Partial<PipelineEvent> = {}

    constructor(team: Team, distinctId: string = new UUIDT().toString()) {
        this.event = {
            event: 'custom event',
            properties: {},
            timestamp: new Date().toISOString(),
            now: new Date().toISOString(),
            ip: null,
            site_url: 'https://example.com',
            uuid: new UUIDT().toString(),
        }
        this.event.distinct_id = distinctId
        this.event.team_id = team.id
    }

    withEvent(event: string) {
        this.event.event = event
        return this
    }

    withProperties(properties: Record<string, any>) {
        this.event.properties = properties
        return this
    }

    withOverrides(overrides: Record<string, any>) {
        this.event = { ...this.event, ...overrides }
        return this
    }

    withTimestamp(timestamp: number) {
        const date = DateTime.fromMillis(timestamp)
        this.event.timestamp = date.toString()
        this.event.now = date.toString()
        return this
    }

    withNow(now: number) {
        const date = DateTime.fromMillis(now)
        this.event.now = date.toString()
        return this
    }

    withGroupProperties(groupType: string, groupKey: string, groupSet?: Record<string, any>) {
        this.event.properties = {
            ...this.event.properties,
            $group_type: groupType,
            $group_key: groupKey,
            ...(groupSet ? { $group_set: groupSet } : {}),
        }
        return this
    }

    build(): PipelineEvent {
        return this.event as PipelineEvent
    }
}

let offsetIncrementer = 0

export function createKafkaMessage(
    event: PipelineEvent,
    token: string,
    timestamp: number = DateTime.now().toMillis()
): Message {
    const captureEvent = {
        uuid: event.uuid,
        distinct_id: event.distinct_id,
        ip: event.ip,
        now: event.now,
        token,
        data: JSON.stringify(event),
    }

    const headers: { [key: string]: Buffer }[] = [
        { token: Buffer.from(token) },
        { distinct_id: Buffer.from(event.distinct_id!) },
    ]
    if (event.timestamp) {
        const timestampMs = DateTime.fromISO(event.timestamp).toMillis()
        headers.push({ timestamp: Buffer.from(timestampMs.toString()) })
    }
    if (event.now) {
        headers.push({ now: Buffer.from(event.now) })
    }

    return {
        key: `${token}:${event.distinct_id}`,
        value: Buffer.from(JSON.stringify(captureEvent)),
        size: 1,
        topic: 'test',
        offset: offsetIncrementer++,
        timestamp: timestamp + offsetIncrementer,
        partition: 1,
        headers,
    }
}

export function createKafkaMessages(events: PipelineEvent[], token: string): Message[] {
    return events.map((e) => createKafkaMessage(e, token))
}

export const waitForKafkaMessages = async (kafkaProducer: KafkaProducerWrapper) => {
    await kafkaProducer.flush()
}

/**
 * After `resetKafka()` recreates topics, ClickHouse's Kafka engine consumers need to
 * reconnect. With the default auto.offset.reset=latest, any messages produced before
 * reconnection are permanently missed. We repeatedly produce probe messages until
 * ClickHouse consumes one, which guarantees at least one lands after reconnection.
 */
export async function waitForClickHouseKafkaConsumer(clickhouse: Clickhouse): Promise<void> {
    const producer = await KafkaProducerWrapper.create(undefined)
    const probeTeamId = -1

    try {
        await waitForExpect(async () => {
            await producer.queueMessages({
                topic: KAFKA_INGESTION_WARNINGS,
                messages: [
                    {
                        value: JSON.stringify({
                            team_id: probeTeamId,
                            type: 'probe',
                            source: 'test-warmup',
                            details: '{}',
                            timestamp: DateTime.utc().toFormat('yyyy-MM-dd HH:mm:ss'),
                        }),
                    },
                ],
            })
            await producer.flush()

            const result = await clickhouse.query<{ count: number }>(
                `SELECT count() as count FROM ingestion_warnings WHERE team_id = ${probeTeamId}`
            )
            expect(Number(result[0]?.count ?? 0)).toBeGreaterThan(0)
        }, 30_000)
    } finally {
        await producer.disconnect()
    }
}

export async function retryClickHouseOperation<T>(
    operation: () => Promise<T>,
    operationName: string,
    maxRetries: number = 3,
    throwOnFailure: boolean = true
): Promise<T | null> {
    let lastError: Error | null = null

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            return await operation()
        } catch (error: any) {
            lastError = error

            const isSocketError =
                error?.message?.includes('socket hang up') ||
                error?.message?.includes('ECONNRESET') ||
                error?.message?.includes('ETIMEDOUT')

            if (isSocketError && attempt < maxRetries) {
                const backoffMs = Math.min(1000 * Math.pow(2, attempt - 1), 10000)
                console.warn(
                    `[DEBUG] ClickHouse ${operationName} failed (attempt ${attempt}/${maxRetries}), retrying in ${backoffMs}ms:`,
                    error?.message
                )
                await new Promise((resolve) => setTimeout(resolve, backoffMs))
                continue
            }

            console.warn(
                `[DEBUG] ClickHouse ${operationName} failed (attempt ${attempt}/${maxRetries}):`,
                error?.message
            )
            break
        }
    }

    if (throwOnFailure && lastError) {
        throw lastError
    } else if (lastError) {
        console.warn(`[DEBUG] ClickHouse ${operationName} failed after all retries (non-fatal):`, lastError?.message)
        return null
    }

    return null
}

export async function fetchEvents(clickhouse: Clickhouse, teamId: number) {
    await retryClickHouseOperation(
        () => clickhouse.exec(`OPTIMIZE TABLE person_distinct_id_overrides FINAL`),
        'OPTIMIZE TABLE person_distinct_id_overrides FINAL',
        3,
        false
    )

    const queryResult = (await retryClickHouseOperation(
        () =>
            clickhouse.query(`
                SELECT *,
                       if(notEmpty(overrides.person_id), overrides.person_id, e.person_id) as person_id
                FROM events e
                FINAL
                LEFT OUTER JOIN (
                    SELECT
                        distinct_id,
                        argMax(person_id, version) as person_id
                      FROM person_distinct_id_overrides
                      FINAL
                      WHERE team_id = ${teamId}
                      GROUP BY distinct_id
                ) AS overrides USING distinct_id
                WHERE team_id = ${teamId}
                ORDER BY timestamp ASC
            `),
        'fetchEvents query',
        3,
        true
    )) as unknown as RawClickHouseEvent[]

    return queryResult.map(parseRawClickHouseEvent)
}

export async function fetchIngestionWarnings(clickhouse: Clickhouse, teamId: number) {
    const queryResult = (await retryClickHouseOperation(
        () =>
            clickhouse.query(`
                SELECT *
                FROM ingestion_warnings
                WHERE team_id = ${teamId}
            `),
        'fetchIngestionWarnings query',
        3,
        true
    )) as any[]

    return queryResult.map((warning: any) => ({ ...warning, details: parseJSON(warning.details) }))
}

export interface IngesterLike {
    start(): Promise<void>
    stop(): Promise<void>
}

/**
 * Set of primitives the test harness exposes to an ingester builder. Built
 * directly from primitive Manager/factory calls — no hub involved.
 */
export interface IngestionTestInfra {
    config: PluginsServerConfig
    postgres: PostgresRouter
    redisPool: RedisPool
    teamManager: TeamManager
    groupRepository: GroupRepository
    personRepository: PersonRepository
    cookielessManager: CookielessManager
    pubSub: PubSub
    geoipService: GeoIPService
    encryptedFields: EncryptedFields
    integrationManager: IntegrationManagerService
    groupTypeManager: GroupTypeManager
}

export interface TeamIngesterTestContext<T extends IngesterLike> {
    infra: IngestionTestInfra
    team: Team
    kafkaProducer: KafkaProducerWrapper
    ingester: T
    token: string
}

export interface TeamIngesterTestConfig {
    teamOverrides?: Partial<Team>
    pluginServerConfig?: Partial<PluginsServerConfig>
}

export type BuildIngester<T extends IngesterLike> = (
    infra: IngestionTestInfra,
    kafkaProducer: KafkaProducerWrapper
) => T

/**
 * Builds a `test` factory that spins up an isolated team + hub + consumer per
 * test. The caller supplies the `buildIngester` function that constructs the
 * consumer under test — different pipelines have different deps.
 */
export function createTestWithTeamIngester<T extends IngesterLike>(
    baseConfig: Partial<PluginsServerConfig>,
    buildIngester: BuildIngester<T>
) {
    return (
        name: string,
        config: TeamIngesterTestConfig = {},
        testFn: (ctx: TeamIngesterTestContext<T>) => Promise<void>
    ) => {
        test(name, async () => {
            const serverConfig: PluginsServerConfig = {
                ...defaultConfig,
                ...baseConfig,
                ...config.pluginServerConfig,
            }

            const postgres = new PostgresRouter(serverConfig, serverConfig.PLUGIN_SERVER_MODE ?? undefined)
            const redisPool = createRedisPoolFromConfig({
                connection: createIngestionRedisConnectionConfig(serverConfig),
                poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
                poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
            })
            const cookielessRedisPool = createRedisPoolFromConfig({
                connection: createCookielessRedisConnectionConfig(serverConfig),
                poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
                poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
            })

            const teamManager = new TeamManager(postgres)
            const pubSub = new PubSub(redisPool)
            await pubSub.start()

            const personhogClient = createPersonHogClient(serverConfig)
            const clientLabel = serverConfig.PLUGIN_SERVER_MODE ?? 'unknown'

            const postgresGroupRepository = new PostgresGroupRepository(postgres)
            const postgresPersonRepository = new PostgresPersonRepository(postgres, {
                calculatePropertiesSize: serverConfig.PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE,
            })
            const personRepository = buildPersonRepository(
                personhogClient,
                postgresPersonRepository,
                serverConfig.PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE,
                serverConfig.PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS,
                clientLabel
            )
            const groupRepository = buildGroupRepository(
                personhogClient,
                postgresGroupRepository,
                serverConfig.PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE,
                serverConfig.PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS,
                clientLabel
            )
            const groupTypeManager = new GroupTypeManager(groupRepository, teamManager)
            const cookielessManager = new CookielessManager(serverConfig, cookielessRedisPool)
            const geoipService = new GeoIPService(serverConfig.MMDB_FILE_LOCATION)
            await geoipService.get()
            const encryptedFields = new EncryptedFields(serverConfig.ENCRYPTION_SALT_KEYS)
            const integrationManager = new IntegrationManagerService(pubSub, postgres, encryptedFields)

            const kafkaProducer = await KafkaProducerWrapper.create(serverConfig.KAFKA_CLIENT_RACK)

            const teamId = Math.floor((Date.now() % 1000000000) + Math.random() * 1000000)
            const userId = teamId
            const organizationId = new UUIDT().toString()

            const newTeam: Team = {
                ...DEFAULT_TEAM,
                id: teamId,
                project_id: teamId as ProjectId,
                organization_id: organizationId,
                uuid: v4(),
                name: teamId.toString(),
                ...config.teamOverrides,
            }
            const userUuid = new UUIDT().toString()
            const organizationMembershipId = new UUIDT().toString()

            await createUserTeamAndOrganization(
                postgres,
                newTeam.id,
                userId,
                userUuid,
                newTeam.organization_id,
                organizationMembershipId,
                config.teamOverrides
            )

            const fetchedTeam = await teamManager.getTeam(newTeam.id)
            if (!fetchedTeam) {
                throw new Error(`Failed to fetch team ${newTeam.id} from database`)
            }

            const infra: IngestionTestInfra = {
                config: serverConfig,
                postgres,
                redisPool,
                teamManager,
                groupRepository,
                personRepository,
                cookielessManager,
                pubSub,
                geoipService,
                encryptedFields,
                integrationManager,
                groupTypeManager,
            }

            const ingester = buildIngester(infra, kafkaProducer)
            // We don't actually use kafka so we skip instantiation for faster tests
            ;(ingester as unknown as { kafkaConsumer: unknown }).kafkaConsumer = {
                connect: jest.fn(),
                disconnect: jest.fn(),
                isHealthy: jest.fn(),
            }

            await ingester.start()
            try {
                await testFn({ infra, team: fetchedTeam, kafkaProducer, ingester, token: fetchedTeam.api_token })
            } finally {
                await ingester.stop()
                await kafkaProducer.disconnect()
                await pubSub.stop()
                await Promise.allSettled([redisPool.drain(), cookielessRedisPool.drain(), postgres.end()])
                await redisPool.clear()
                await cookielessRedisPool.clear()
                cookielessManager.shutdown()
            }
        })
    }
}
