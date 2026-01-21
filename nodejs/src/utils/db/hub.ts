import { DateTime } from 'luxon'
import { types as pgTypes } from 'pg'

import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { EncryptedFields } from '../../cdp/utils/encryption-utils'
import { defaultConfig } from '../../config/config'
import { CookielessManager } from '../../ingestion/cookieless/cookieless-manager'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, PluginsServerConfig } from '../../types'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { ClickhouseGroupRepository } from '../../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { PostgresGroupRepository } from '../../worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresPersonRepository } from '../../worker/ingestion/persons/repositories/postgres-person-repository'
import { isTestEnv } from '../env-utils'
import { GeoIPService } from '../geoip'
import { logger } from '../logger'
import { PubSub } from '../pubsub'
import { TeamManager } from '../team-manager'
import { PostgresRouter } from './postgres'
import { createRedisPoolFromConfig } from './redis'

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

export async function createHub(config: Partial<PluginsServerConfig> = {}): Promise<Hub> {
    logger.info('ℹ️', `Connecting to all services:`)

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }

    logger.info('🤔', `Connecting to Kafka...`)

    const kafkaProducer = await KafkaProducerWrapper.create(serverConfig.KAFKA_CLIENT_RACK)
    logger.info('👍', `Kafka ready`)

    const postgres = new PostgresRouter(serverConfig)
    logger.info('👍', `Postgres Router ready`)

    logger.info('🤔', `Connecting to ingestion Redis...`)
    const redisPool = createRedisPoolFromConfig({
        connection: serverConfig.INGESTION_REDIS_HOST
            ? {
                  url: serverConfig.INGESTION_REDIS_HOST,
                  options: { port: serverConfig.INGESTION_REDIS_PORT },
                  name: 'ingestion-redis',
              }
            : serverConfig.POSTHOG_REDIS_HOST
              ? {
                    url: serverConfig.POSTHOG_REDIS_HOST,
                    options: { port: serverConfig.POSTHOG_REDIS_PORT, password: serverConfig.POSTHOG_REDIS_PASSWORD },
                    name: 'ingestion-redis',
                }
              : { url: serverConfig.REDIS_URL, name: 'ingestion-redis' },
        poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
        poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
    })
    logger.info('👍', `Ingestion Redis ready`)

    logger.info('🤔', `Connecting to cookieless Redis...`)
    const cookielessRedisPool = createRedisPoolFromConfig({
        connection: serverConfig.COOKIELESS_REDIS_HOST
            ? {
                  url: serverConfig.COOKIELESS_REDIS_HOST,
                  options: { port: serverConfig.COOKIELESS_REDIS_PORT ?? 6379 },
                  name: 'cookieless-redis',
              }
            : { url: serverConfig.REDIS_URL, name: 'cookieless-redis' },
        poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
        poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
    })
    logger.info('👍', `Cookieless Redis ready`)

    const teamManager = new TeamManager(postgres)
    logger.info('🤔', `Connecting to PostHog Redis...`)
    const posthogRedisPool = createRedisPoolFromConfig({
        connection: serverConfig.POSTHOG_REDIS_HOST
            ? {
                  url: serverConfig.POSTHOG_REDIS_HOST,
                  options: { port: serverConfig.POSTHOG_REDIS_PORT, password: serverConfig.POSTHOG_REDIS_PASSWORD },
                  name: 'posthog-redis',
              }
            : { url: serverConfig.REDIS_URL, name: 'posthog-redis' },
        poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
        poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
    })
    logger.info('👍', `PostHog Redis ready`)

    const pubSub = new PubSub(redisPool)
    await pubSub.start()

    const groupRepository = new PostgresGroupRepository(postgres)
    const groupTypeManager = new GroupTypeManager(groupRepository, teamManager)

    const personRepositoryOptions = {
        calculatePropertiesSize: serverConfig.PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE,
    }
    const personRepository = new PostgresPersonRepository(postgres, personRepositoryOptions)

    const clickhouseGroupRepository = new ClickhouseGroupRepository(kafkaProducer)
    const cookielessManager = new CookielessManager(serverConfig, cookielessRedisPool, teamManager)
    const geoipService = new GeoIPService(serverConfig)
    await geoipService.get()
    const encryptedFields = new EncryptedFields(serverConfig.ENCRYPTION_SALT_KEYS)
    const integrationManager = new IntegrationManagerService(pubSub, postgres, encryptedFields)
    const quotaLimiting = new QuotaLimiting(posthogRedisPool, teamManager)
    const internalCaptureService = new InternalCaptureService(serverConfig)

    const hub: Hub = {
        ...serverConfig,
        postgres,
        redisPool,
        posthogRedisPool,
        cookielessRedisPool,
        kafkaProducer,
        groupTypeManager,
        teamManager,
        groupRepository,
        clickhouseGroupRepository,
        personRepository,
        geoipService,
        encryptedFields,
        cookielessManager,
        pubSub,
        integrationManager,
        quotaLimiting,
        internalCaptureService,
    }

    return hub
}

export const closeHub = async (hub: Hub): Promise<void> => {
    logger.info('💤', 'Closing hub...')
    logger.info('💤', 'Closing kafka, redis, postgres...')
    await hub.pubSub.stop()
    await Promise.allSettled([
        hub.kafkaProducer.disconnect(),
        hub.redisPool.drain(),
        hub.posthogRedisPool.drain(),
        hub.cookielessRedisPool.drain(),
        hub.postgres?.end(),
    ])
    await hub.redisPool.clear()
    await hub.posthogRedisPool.clear()
    await hub.cookielessRedisPool.clear()
    logger.info('💤', 'Closing cookieless manager...')
    hub.cookielessManager.shutdown()

    if (isTestEnv()) {
        // Break circular references to allow the hub to be GCed when running unit tests
        // TODO: change these structs to not directly reference the hub
        ;(hub as any).eventsProcessor = undefined
        ;(hub as any).appMetrics = undefined
    }
    logger.info('💤', 'Hub closed!')
}
