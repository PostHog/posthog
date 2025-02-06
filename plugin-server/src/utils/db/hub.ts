import ClickHouse from '@posthog/clickhouse'
import * as fs from 'fs'
import { DateTime } from 'luxon'
import * as path from 'path'
import { types as pgTypes } from 'pg'

import { getPluginServerCapabilities } from '../../capabilities'
import { EncryptedFields } from '../../cdp/encryption-utils'
import { createCookielessConfig, defaultConfig } from '../../config/config'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { getObjectStorage } from '../../main/services/object_storage'
import { Hub, PluginServerCapabilities, PluginsServerConfig } from '../../types'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { OrganizationManager } from '../../worker/ingestion/organization-manager'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { CookielessSaltManager } from '../cookieless/cookielessServerHashStep'
import { isTestEnv } from '../env-utils'
import { status } from '../status'
import { UUIDT } from '../utils'
import { Celery } from './celery'
import { DB } from './db'
import { PostgresRouter } from './postgres'
import { createRedisPool } from './redis'

// `node-postgres` would return dates as plain JS Date objects, which would use the local timezone.
// This converts all date fields to a proper luxon UTC DateTime and then casts them to a string
// Unfortunately this must be done on a global object before initializing the `Pool`
pgTypes.setTypeParser(1083 /* types.TypeId.TIME */, (timeStr) =>
    timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
)
pgTypes.setTypeParser(1114 /* types.TypeId.TIMESTAMP */, (timeStr) =>
    timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
)
pgTypes.setTypeParser(1184 /* types.TypeId.TIMESTAMPTZ */, (timeStr) =>
    timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
)

export function createEventsToDropByToken(eventsToDropByTokenStr?: string): Map<string, string[]> {
    const eventsToDropByToken: Map<string, string[]> = new Map()
    if (eventsToDropByTokenStr) {
        eventsToDropByTokenStr.split(',').forEach((pair) => {
            const separatorIndex = pair.indexOf(':')
            const token = pair.substring(0, separatorIndex)
            const distinctID = pair.substring(separatorIndex + 1)
            eventsToDropByToken.set(token, [...(eventsToDropByToken.get(token) || []), distinctID])
        })
    }
    return eventsToDropByToken
}

export async function createHub(
    config: Partial<PluginsServerConfig> = {},
    capabilities: PluginServerCapabilities | null = null
): Promise<Hub> {
    status.info('ℹ️', `Connecting to all services:`)

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }
    if (capabilities === null) {
        capabilities = getPluginServerCapabilities(serverConfig)
    }
    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)
    const instanceId = new UUIDT()

    status.info('🤔', `Connecting to ClickHouse...`)
    const clickhouse = new ClickHouse({
        // We prefer to run queries on the offline cluster.
        host: serverConfig.CLICKHOUSE_OFFLINE_CLUSTER_HOST ?? serverConfig.CLICKHOUSE_HOST,
        port: serverConfig.CLICKHOUSE_SECURE ? 8443 : 8123,
        protocol: serverConfig.CLICKHOUSE_SECURE ? 'https:' : 'http:',
        user: serverConfig.CLICKHOUSE_USER,
        password: serverConfig.CLICKHOUSE_PASSWORD || undefined,
        dataObjects: true,
        queryOptions: {
            database: serverConfig.CLICKHOUSE_DATABASE,
            output_format_json_quote_64bit_integers: false,
        },
        ca: serverConfig.CLICKHOUSE_CA
            ? fs.readFileSync(path.join(serverConfig.BASE_DIR, serverConfig.CLICKHOUSE_CA)).toString()
            : undefined,
        rejectUnauthorized: serverConfig.CLICKHOUSE_CA ? false : undefined,
    })
    status.info('👍', `ClickHouse ready`)

    status.info('🤔', `Connecting to Kafka...`)

    const kafkaProducer = await KafkaProducerWrapper.create(serverConfig)
    status.info('👍', `Kafka ready`)

    const postgres = new PostgresRouter(serverConfig)
    // TODO: assert tables are reachable (async calls that cannot be in a constructor)
    status.info('👍', `Postgres Router ready`)

    status.info('🤔', `Connecting to Redis...`)
    const redisPool = createRedisPool(serverConfig, 'ingestion')
    status.info('👍', `Redis ready`)

    status.info('🤔', `Connecting to object storage...`)

    const objectStorage = getObjectStorage(serverConfig)
    if (objectStorage) {
        status.info('👍', 'Object storage ready')
    } else {
        status.warn('🪣', `Object storage could not be created`)
    }

    const db = new DB(
        postgres,
        redisPool,
        kafkaProducer,
        clickhouse,
        serverConfig.PLUGINS_DEFAULT_LOG_LEVEL,
        serverConfig.PERSON_INFO_CACHE_TTL
    )
    const teamManager = new TeamManager(postgres, serverConfig)
    const organizationManager = new OrganizationManager(postgres, teamManager)

    const groupTypeManager = new GroupTypeManager(postgres, teamManager)

    const cookielessConfig = createCookielessConfig(serverConfig)
    const cookielessSaltManager = new CookielessSaltManager(db, cookielessConfig)

    const hub: Hub = {
        ...serverConfig,
        instanceId,
        capabilities,
        db,
        postgres,
        redisPool,
        clickhouse,
        kafkaProducer,
        objectStorage: objectStorage,
        groupTypeManager,

        teamManager,
        organizationManager,
        eventsToDropByToken: createEventsToDropByToken(process.env.DROP_EVENTS_BY_TOKEN_DISTINCT_ID),
        eventsToSkipPersonsProcessingByToken: createEventsToDropByToken(
            process.env.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID
        ),
        encryptedFields: new EncryptedFields(serverConfig),
        celery: new Celery(serverConfig),
        cookielessConfig,
        cookielessSaltManager,
    }

    return hub as Hub
}

export const closeHub = async (hub: Hub): Promise<void> => {
    await Promise.allSettled([hub.kafkaProducer.disconnect(), hub.redisPool.drain(), hub.postgres?.end()])
    await hub.redisPool.clear()
    hub.cookielessSaltManager.shutdown()

    if (isTestEnv()) {
        // Break circular references to allow the hub to be GCed when running unit tests
        // TODO: change these structs to not directly reference the hub
        ;(hub as any).eventsProcessor = undefined
        ;(hub as any).appMetrics = undefined
    }
}

export type KafkaConfig = Pick<
    PluginsServerConfig,
    | 'KAFKA_HOSTS'
    | 'KAFKA_PRODUCER_HOSTS'
    | 'KAFKA_SECURITY_PROTOCOL'
    | 'KAFKA_PRODUCER_SECURITY_PROTOCOL'
    | 'KAFKA_CLIENT_ID'
    | 'KAFKA_PRODUCER_CLIENT_ID'
    | 'KAFKA_CLIENT_RACK'
    | 'KAFKAJS_LOG_LEVEL'
    | 'KAFKA_CLIENT_CERT_B64'
    | 'KAFKA_CLIENT_CERT_KEY_B64'
    | 'KAFKA_TRUSTED_CERT_B64'
    | 'KAFKA_SASL_MECHANISM'
    | 'KAFKA_SASL_USER'
    | 'KAFKA_SASL_PASSWORD'
>
