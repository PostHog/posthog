import { DateTime } from 'luxon'
import { types as pgTypes } from 'pg'

import { CookielessManager } from '~/src/ingestion/cookieless/cookieless-manager'

import { getPluginServerCapabilities } from '../capabilities'
import { EncryptedFields } from '../cdp/encryption-utils'
import { defaultConfig } from '../config/config'
import { KafkaProducerWrapper } from '../kafka/producer'
import { GroupTypeManager } from '../services/group-type-manager'
import { OrganizationManager } from '../services/organization-manager'
import { TeamManager } from '../services/team-manager'
import { Config, Hub, PluginServerCapabilities } from '../types'
import { Celery } from './celery'
import { GeoIPService } from './geoip'
import { getObjectStorage } from './object_storage'
import { PostgresRouter } from './postgres'
import { createRedisPool } from './redis'
import { status } from './status'

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
    config: Partial<Config> = {},
    capabilities: PluginServerCapabilities | null = null
): Promise<Hub> {
    status.info('ℹ️', `Connecting to all services:`)

    const serverConfig: Config = {
        ...defaultConfig,
        ...config,
    }
    if (capabilities === null) {
        capabilities = getPluginServerCapabilities(serverConfig)
    }
    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)

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

    const teamManager = new TeamManager(postgres, serverConfig)
    const organizationManager = new OrganizationManager(postgres, teamManager)

    const groupTypeManager = new GroupTypeManager(postgres, teamManager)

    const cookielessManager = new CookielessManager(serverConfig, redisPool, teamManager)

    const hub: Hub = {
        ...serverConfig,
        capabilities,
        postgres,
        redisPool,
        kafkaProducer,
        objectStorage: objectStorage,
        groupTypeManager,
        geoipService: new GeoIPService(serverConfig),
        teamManager,
        organizationManager,
        eventsToDropByToken: createEventsToDropByToken(serverConfig.DROP_EVENTS_BY_TOKEN_DISTINCT_ID),
        eventsToSkipPersonsProcessingByToken: createEventsToDropByToken(
            serverConfig.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID
        ),
        encryptedFields: new EncryptedFields(serverConfig),
        celery: new Celery(serverConfig),
        cookielessManager,
    }

    return hub as Hub
}

export const closeHub = async (hub: Hub): Promise<void> => {
    await Promise.allSettled([hub.kafkaProducer.disconnect(), hub.redisPool.drain(), hub.postgres?.end()])
    await hub.redisPool.clear()
    hub.cookielessManager.shutdown()
}

export type KafkaConfig = Pick<
    Config,
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
