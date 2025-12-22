import { DateTime } from 'luxon'
import { types as pgTypes } from 'pg'

import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { getPluginServerCapabilities } from '../../capabilities'
import { EncryptedFields } from '../../cdp/utils/encryption-utils'
import { buildIntegerMatcher, defaultConfig } from '../../config/config'
import { CookielessManager } from '../../ingestion/cookieless/cookieless-manager'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, PluginServerCapabilities, PluginsServerConfig } from '../../types'
import { AppMetrics } from '../../worker/ingestion/app-metrics'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { ClickhouseGroupRepository } from '../../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { PostgresGroupRepository } from '../../worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresPersonRepository } from '../../worker/ingestion/persons/repositories/postgres-person-repository'
import { ActionManagerCDP } from '../action-manager-cdp'
import { isTestEnv } from '../env-utils'
import { GeoIPService } from '../geoip'
import { logger } from '../logger'
import { PubSub } from '../pubsub'
import { TeamManager } from '../team-manager'
import { UUIDT } from '../utils'
import { PluginsApiKeyManager } from './../../worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './../../worker/vm/extensions/helpers/root-acess-manager'
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
    logger.info('ℹ️', `Connecting to all services:`)

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }
    if (capabilities === null) {
        capabilities = getPluginServerCapabilities(serverConfig)
    }
    const instanceId = new UUIDT()

    logger.info('🤔', `Connecting to Kafka...`)

    const kafkaProducer = await KafkaProducerWrapper.create(serverConfig)
    logger.info('👍', `Kafka ready`)

    const postgres = new PostgresRouter(serverConfig)
    logger.info('👍', `Postgres Router ready`)

    logger.info('🤔', `Connecting to ingestion Redis...`)
    const redisPool = createRedisPool(serverConfig, 'ingestion')
    logger.info('👍', `Ingestion Redis ready`)

    logger.info('🤔', `Connecting to cookieless Redis...`)
    const cookielessRedisPool = createRedisPool(serverConfig, 'cookieless')
    logger.info('👍', `Cookieless Redis ready`)

    const db = new DB(
        postgres,
        redisPool,
        cookielessRedisPool,
        kafkaProducer,
        serverConfig.PLUGINS_DEFAULT_LOG_LEVEL,
        serverConfig.PERSON_INFO_CACHE_TTL
    )
    const teamManager = new TeamManager(postgres)
    const pluginsApiKeyManager = new PluginsApiKeyManager(db)
    const rootAccessManager = new RootAccessManager(db)
    const pubSub = new PubSub(serverConfig)
    await pubSub.start()
    const actionManagerCDP = new ActionManagerCDP(postgres)

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
    const encryptedFields = new EncryptedFields(serverConfig)
    const integrationManager = new IntegrationManagerService(pubSub, postgres, encryptedFields)
    const quotaLimiting = new QuotaLimiting(serverConfig, teamManager)
    const internalCaptureService = new InternalCaptureService(serverConfig)

    const hub: Hub = {
        ...serverConfig,
        instanceId,
        capabilities,
        db,
        postgres,
        redisPool,
        cookielessRedisPool,
        kafkaProducer,
        groupTypeManager,

        plugins: new Map(),
        pluginConfigs: new Map(),
        pluginConfigsPerTeam: new Map(),
        pluginConfigSecrets: new Map(),
        pluginConfigSecretLookup: new Map(),
        pluginSchedule: null,

        teamManager,
        pluginsApiKeyManager,
        rootAccessManager,
        groupRepository,
        clickhouseGroupRepository,
        personRepository,
        actionManagerCDP,
        geoipService,
        pluginConfigsToSkipElementsParsing: buildIntegerMatcher(process.env.SKIP_ELEMENTS_PARSING_PLUGINS, true),
        eventsToDropByToken: createEventsToDropByToken(process.env.DROP_EVENTS_BY_TOKEN_DISTINCT_ID),
        appMetrics: new AppMetrics(
            kafkaProducer,
            serverConfig.APP_METRICS_FLUSH_FREQUENCY_MS,
            serverConfig.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
        ),
        encryptedFields,
        celery: new Celery(serverConfig),
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
    if (!isTestEnv()) {
        await hub.appMetrics?.flush()
    }
    logger.info('💤', 'Closing kafka, redis, postgres...')
    await hub.pubSub.stop()
    await Promise.allSettled([hub.kafkaProducer.disconnect(), hub.redisPool.drain(), hub.postgres?.end()])
    await hub.redisPool.clear()
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
