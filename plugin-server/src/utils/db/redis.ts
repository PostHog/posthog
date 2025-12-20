import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { PluginsServerConfig, RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { killGracefully } from '../../utils/utils'
import { captureException } from '../posthog'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

export type REDIS_SERVER_KIND = 'posthog' | 'ingestion' | 'session-recording' | 'cookieless' | 'cdp' | 'logs'

/** Minimal config needed for Redis pool creation */
export type RedisPoolConfig = Pick<
    PluginsServerConfig,
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'POSTHOG_REDIS_HOST'
    | 'POSTHOG_REDIS_PORT'
    | 'POSTHOG_REDIS_PASSWORD'
    | 'INGESTION_REDIS_HOST'
    | 'INGESTION_REDIS_PORT'
    | 'POSTHOG_SESSION_RECORDING_REDIS_HOST'
    | 'POSTHOG_SESSION_RECORDING_REDIS_PORT'
    | 'COOKIELESS_REDIS_HOST'
    | 'COOKIELESS_REDIS_PORT'
    | 'CDP_REDIS_HOST'
    | 'CDP_REDIS_PORT'
    | 'CDP_REDIS_PASSWORD'
    | 'LOGS_REDIS_HOST'
    | 'LOGS_REDIS_PORT'
    | 'LOGS_REDIS_PASSWORD'
    | 'LOGS_REDIS_TLS'
>

/** CDP-specific redis config */
export type CdpRedisPoolConfig = Pick<
    PluginsServerConfig,
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'CDP_REDIS_HOST'
    | 'CDP_REDIS_PORT'
    | 'CDP_REDIS_PASSWORD'
>

/** Logs-specific redis config */
export type LogsRedisPoolConfig = Pick<
    PluginsServerConfig,
    | 'REDIS_URL'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'LOGS_REDIS_HOST'
    | 'LOGS_REDIS_PORT'
    | 'LOGS_REDIS_PASSWORD'
    | 'LOGS_REDIS_TLS'
>

// Overload for CDP-specific config
export function getRedisConnectionOptions(
    serverConfig: CdpRedisPoolConfig,
    kind: 'cdp'
): { url: string; options?: RedisOptions }
// Overload for Logs-specific config
export function getRedisConnectionOptions(
    serverConfig: LogsRedisPoolConfig,
    kind: 'logs'
): { url: string; options?: RedisOptions }
// General overload
export function getRedisConnectionOptions(
    serverConfig: RedisPoolConfig,
    kind: REDIS_SERVER_KIND
): { url: string; options?: RedisOptions }
// Implementation
export function getRedisConnectionOptions(
    serverConfig: RedisPoolConfig | CdpRedisPoolConfig | LogsRedisPoolConfig,
    kind: REDIS_SERVER_KIND
): {
    url: string
    options?: RedisOptions
} {
    // Cast to full config - the overloads ensure correct usage
    const config = serverConfig as RedisPoolConfig
    const fallback = { url: config.REDIS_URL }
    switch (kind) {
        case 'posthog':
            return config.POSTHOG_REDIS_HOST
                ? {
                      url: config.POSTHOG_REDIS_HOST,
                      options: {
                          port: config.POSTHOG_REDIS_PORT,
                          password: config.POSTHOG_REDIS_PASSWORD,
                      },
                  }
                : fallback
        case 'ingestion':
            return config.INGESTION_REDIS_HOST
                ? {
                      url: config.INGESTION_REDIS_HOST,
                      options: {
                          port: config.INGESTION_REDIS_PORT,
                      },
                  }
                : config.POSTHOG_REDIS_HOST
                  ? {
                        url: config.POSTHOG_REDIS_HOST,
                        options: {
                            port: config.POSTHOG_REDIS_PORT,
                            password: config.POSTHOG_REDIS_PASSWORD,
                        },
                    }
                  : fallback
        case 'session-recording':
            return config.POSTHOG_SESSION_RECORDING_REDIS_HOST
                ? {
                      url: config.POSTHOG_SESSION_RECORDING_REDIS_HOST,
                      options: {
                          port: config.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379,
                      },
                  }
                : fallback
        case 'cookieless':
            return config.COOKIELESS_REDIS_HOST
                ? {
                      url: config.COOKIELESS_REDIS_HOST,
                      options: {
                          port: config.COOKIELESS_REDIS_PORT ?? 6379,
                      },
                  }
                : fallback
        case 'cdp':
            return config.CDP_REDIS_HOST
                ? {
                      url: config.CDP_REDIS_HOST,
                      options: {
                          port: config.CDP_REDIS_PORT,
                          password: config.CDP_REDIS_PASSWORD,
                      },
                  }
                : fallback
        case 'logs':
            return config.LOGS_REDIS_HOST
                ? {
                      url: config.LOGS_REDIS_HOST,
                      options: {
                          port: config.LOGS_REDIS_PORT,
                          // TLS is an object that lets you define certificate, ca, etc
                          // we just want the default config so weirdly we pass empty object to enable it
                          tls: config.LOGS_REDIS_TLS ? {} : undefined,
                      },
                  }
                : fallback
    }
}

// Overload for CDP-specific config
export function createRedis(serverConfig: CdpRedisPoolConfig, kind: 'cdp'): Promise<Redis.Redis>
// Overload for Logs-specific config
export function createRedis(serverConfig: LogsRedisPoolConfig, kind: 'logs'): Promise<Redis.Redis>
// General overload
export function createRedis(serverConfig: RedisPoolConfig, kind: REDIS_SERVER_KIND): Promise<Redis.Redis>
// Implementation
export async function createRedis(
    serverConfig: RedisPoolConfig | CdpRedisPoolConfig | LogsRedisPoolConfig,
    kind: REDIS_SERVER_KIND
): Promise<Redis.Redis> {
    // Cast to full config - the overloads ensure correct usage at call sites
    const { url, options } = getRedisConnectionOptions(serverConfig as RedisPoolConfig, kind)
    return createRedisClient(url, options)
}

export async function createRedisClient(url: string, options?: RedisOptions): Promise<Redis.Redis> {
    const redis = new Redis(url, {
        ...options,
        maxRetriesPerRequest: -1,
    })
    let errorCounter = 0
    redis
        .on('error', (error) => {
            errorCounter++
            captureException(error)
            if (errorCounter > REDIS_ERROR_COUNTER_LIMIT) {
                logger.error('😡', 'Redis error encountered! url:', url, ' Enough of this, I quit!', error)
                killGracefully()
            } else {
                logger.error('🔴', 'Redis error encountered! url:', url, ' Trying to reconnect...', error)
            }
        })
        .on('ready', () => {
            if (process.env.NODE_ENV !== 'test') {
                logger.info('✅', 'Connected to Redis!', url)
            }
        })
    await redis.info()
    return redis
}

export function createRedisPool(options: PluginsServerConfig, kind: REDIS_SERVER_KIND): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createRedis(options, kind),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: options.REDIS_POOL_MIN_SIZE,
            max: options.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}
