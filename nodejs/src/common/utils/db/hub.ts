import { IntegrationManagerService } from '@posthog/hog-engine/cdp/services/managers/integration-manager.service'
import { PostgresIntegrationSource } from '@posthog/hog-engine/cdp/services/managers/postgres-integration-source'
import { EncryptedFields } from '@posthog/hog-engine/cdp/utils/encryption-utils'
import { GroupTypeManager } from '@posthog/ingestion-common/groups/group-type-manager'
import { PostgresGroupRepository } from '@posthog/ingestion-common/groups/repositories/postgres-group-repository'
import {
    buildGroupRepository,
    buildPersonRepository,
    createPersonHogClient,
} from '@posthog/ingestion-common/personhog/index'
import { PostgresPersonRepository } from '@posthog/ingestion-common/persons/repositories/postgres-person-repository'
import {
    createIngestionRedisConnectionConfig,
    createPosthogRedisConnectionConfig,
} from '@posthog/node-common/config/redis-pools'
import { QuotaLimiting } from '@posthog/node-common/services/quota-limiting.service'
import { PostgresRouter, installPostgresTypeParsers } from '@posthog/node-common/utils/db/postgres'
import { createRedisPoolFromConfig } from '@posthog/node-common/utils/db/redis'
import { isTestEnv } from '@posthog/node-common/utils/env-utils'
import { GeoIPService } from '@posthog/node-common/utils/geoip'
import { logger } from '@posthog/node-common/utils/logger'
import { PubSub } from '@posthog/node-common/utils/pubsub'
import { TeamManager } from '@posthog/node-common/utils/team-manager'

import { defaultConfig } from '~/common/config/config'
import { Hub, PluginsServerConfig } from '~/types'

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
        // createHub is legacy/test-only; ingestion configures this on its own infra (see createIngestionTestInfra).
        calculatePropertiesSize: 0,
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

    const geoipService = new GeoIPService(serverConfig.MMDB_FILE_LOCATION)
    await geoipService.get()
    const encryptedFields = new EncryptedFields(serverConfig.ENCRYPTION_SALT_KEYS)
    const integrationManager = new IntegrationManagerService(
        pubSub,
        new PostgresIntegrationSource(postgres, encryptedFields)
    )
    const quotaLimiting = new QuotaLimiting(posthogRedisPool, teamManager)

    const hub: Hub = {
        ...serverConfig,
        postgres,
        redisPool,
        posthogRedisPool,
        groupTypeManager,
        teamManager,
        groupRepository,
        personRepository,
        geoipService,
        encryptedFields,
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
    await Promise.allSettled([hub.redisPool.drain(), hub.posthogRedisPool.drain(), hub.postgres?.end()])
    await hub.redisPool.clear()
    await hub.posthogRedisPool.clear()

    if (isTestEnv()) {
        // Break circular references to allow the hub to be GCed when running unit tests
        // TODO: change these structs to not directly reference the hub
        ;(hub as any).eventsProcessor = undefined
        ;(hub as any).appMetrics = undefined
    }
    logger.info('💤', 'Hub closed!')
}
