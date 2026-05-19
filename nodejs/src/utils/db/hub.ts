import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { EncryptedFields } from '../../cdp/utils/encryption-utils'
import { defaultConfig } from '../../config/config'
import {
    createCookielessRedisConnectionConfig,
    createIngestionRedisConnectionConfig,
    createPosthogRedisConnectionConfig,
} from '../../config/redis-pools'
import { CookielessManager } from '../../ingestion/cookieless/cookieless-manager'
import { buildGroupRepository, buildPersonRepository, createPersonHogClient } from '../../ingestion/personhog'
import { Hub, PluginsServerConfig } from '../../types'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { PostgresGroupRepository } from '../../worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresPersonRepository } from '../../worker/ingestion/persons/repositories/postgres-person-repository'
import { isTestEnv } from '../env-utils'
import { GeoIPService } from '../geoip'
import { logger } from '../logger'
import { PubSub } from '../pubsub'
import { TeamManager } from '../team-manager'
import { PostgresRouter, installPostgresTypeParsers } from './postgres'
import { createRedisPoolFromConfig } from './redis'

// Ensure type parsers are installed for any code path that uses hub.ts directly
// (many test files still use createHub instead of PluginServer)
installPostgresTypeParsers()

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

    const postgres = new PostgresRouter(serverConfig, serverConfig.PLUGIN_SERVER_MODE ?? undefined)
    logger.info('👍', `Postgres Router ready`)

    logger.info('🤔', `Connecting to ingestion Redis...`)
    const redisPool = createRedisPoolFromConfig({
        connection: createIngestionRedisConnectionConfig(serverConfig),
        poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
        poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
    })
    logger.info('👍', `Ingestion Redis ready`)

    logger.info('🤔', `Connecting to cookieless Redis...`)
    const cookielessRedisPool = createRedisPoolFromConfig({
        connection: createCookielessRedisConnectionConfig(serverConfig),
        poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
        poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
    })
    logger.info('👍', `Cookieless Redis ready`)

    const teamManager = new TeamManager(postgres)
    logger.info('🤔', `Connecting to PostHog Redis...`)
    const posthogRedisPool = createRedisPoolFromConfig({
        connection: createPosthogRedisConnectionConfig(serverConfig),
        poolMinSize: serverConfig.REDIS_POOL_MIN_SIZE,
        poolMaxSize: serverConfig.REDIS_POOL_MAX_SIZE,
    })
    logger.info('👍', `PostHog Redis ready`)

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
    const quotaLimiting = new QuotaLimiting(posthogRedisPool, teamManager)

    const hub: Hub = {
        ...serverConfig,
        postgres,
        redisPool,
        posthogRedisPool,
        cookielessRedisPool,
        groupTypeManager,
        teamManager,
        groupRepository,
        personRepository,
        geoipService,
        encryptedFields,
        cookielessManager,
        pubSub,
        integrationManager,
        quotaLimiting,
    }

    return hub
}

export const closeHub = async (hub: Hub): Promise<void> => {
    logger.info('💤', 'Closing hub...')
    logger.info('💤', 'Closing kafka, redis, postgres...')
    await hub.pubSub.stop()
    await Promise.allSettled([
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
