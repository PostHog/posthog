import { defaultConfig } from '~/config/config'
import { createIngestionRedisConnectionConfig, createPosthogRedisConnectionConfig } from '~/config/redis-pools'
import { QuotaLimiting } from '~/services/quota-limiting.service'
import { Hub, PluginsServerConfig } from '~/types'
import { PostgresRouter, installPostgresTypeParsers } from '~/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/utils/db/redis'
import { isTestEnv } from '~/utils/env-utils'
import { GeoIPService } from '~/utils/geoip'
import { logger } from '~/utils/logger'
import { PubSub } from '~/utils/pubsub'
import { TeamManager } from '~/utils/team-manager'

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

    const geoipService = new GeoIPService(serverConfig.MMDB_FILE_LOCATION)
    await geoipService.get()
    const quotaLimiting = new QuotaLimiting(posthogRedisPool, teamManager)

    const hub: Hub = {
        ...serverConfig,
        postgres,
        redisPool,
        posthogRedisPool,
        teamManager,
        geoipService,
        pubSub,
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
