import { createPool } from 'generic-pool'
import Redis, { RedisOptions } from 'ioredis'

import { PluginsServerConfig, RedisPool } from '../../types'
import { logger } from '../../utils/logger'
import { killGracefully } from '../../utils/utils'
import { captureException } from '../posthog'

/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

/** Base redis pool config with common pool settings */
export type BaseRedisPoolConfig = Pick<PluginsServerConfig, 'REDIS_URL' | 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'>

/** Posthog redis config */
export type PosthogRedisPoolConfig = BaseRedisPoolConfig &
    Pick<PluginsServerConfig, 'POSTHOG_REDIS_HOST' | 'POSTHOG_REDIS_PORT' | 'POSTHOG_REDIS_PASSWORD'>

/** Ingestion redis config (falls back to posthog redis) */
export type IngestionRedisPoolConfig = PosthogRedisPoolConfig &
    Pick<PluginsServerConfig, 'INGESTION_REDIS_HOST' | 'INGESTION_REDIS_PORT'>

/** Cookieless redis config */
export type CookielessRedisPoolConfig = BaseRedisPoolConfig &
    Pick<PluginsServerConfig, 'COOKIELESS_REDIS_HOST' | 'COOKIELESS_REDIS_PORT'>

/** Session-recording redis config */
export type SessionRecordingRedisPoolConfig = BaseRedisPoolConfig &
    Pick<PluginsServerConfig, 'POSTHOG_SESSION_RECORDING_REDIS_HOST' | 'POSTHOG_SESSION_RECORDING_REDIS_PORT'>

/** CDP redis config */
export type CdpRedisPoolConfig = BaseRedisPoolConfig &
    Pick<PluginsServerConfig, 'CDP_REDIS_HOST' | 'CDP_REDIS_PORT' | 'CDP_REDIS_PASSWORD'>

/** Logs redis config */
export type LogsRedisPoolConfig = BaseRedisPoolConfig &
    Pick<PluginsServerConfig, 'LOGS_REDIS_HOST' | 'LOGS_REDIS_PORT' | 'LOGS_REDIS_PASSWORD' | 'LOGS_REDIS_TLS'>

/** Union of all redis pool configs */
export type RedisPoolConfig =
    | PosthogRedisPoolConfig
    | IngestionRedisPoolConfig
    | CookielessRedisPoolConfig
    | SessionRecordingRedisPoolConfig
    | CdpRedisPoolConfig
    | LogsRedisPoolConfig

// Legacy alias
export type SessionRecordingRedisConfig = SessionRecordingRedisPoolConfig

// Type-safe Redis connection options getters (no casts needed)
export function getCdpRedisConnectionOptions(config: CdpRedisPoolConfig): { url: string; options?: RedisOptions } {
    return config.CDP_REDIS_HOST
        ? {
              url: config.CDP_REDIS_HOST,
              options: {
                  port: config.CDP_REDIS_PORT,
                  password: config.CDP_REDIS_PASSWORD,
              },
          }
        : { url: config.REDIS_URL }
}

export function getLogsRedisConnectionOptions(config: LogsRedisPoolConfig): { url: string; options?: RedisOptions } {
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
        : { url: config.REDIS_URL }
}

export function getSessionRecordingRedisConnectionOptions(config: SessionRecordingRedisConfig): {
    url: string
    options?: RedisOptions
} {
    return config.POSTHOG_SESSION_RECORDING_REDIS_HOST
        ? {
              url: config.POSTHOG_SESSION_RECORDING_REDIS_HOST,
              options: {
                  port: config.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379,
              },
          }
        : { url: config.REDIS_URL }
}

export function getPosthogRedisConnectionOptions(config: PosthogRedisPoolConfig): {
    url: string
    options?: RedisOptions
} {
    return config.POSTHOG_REDIS_HOST
        ? {
              url: config.POSTHOG_REDIS_HOST,
              options: {
                  port: config.POSTHOG_REDIS_PORT,
                  password: config.POSTHOG_REDIS_PASSWORD,
              },
          }
        : { url: config.REDIS_URL }
}

export function getIngestionRedisConnectionOptions(config: IngestionRedisPoolConfig): {
    url: string
    options?: RedisOptions
} {
    return config.INGESTION_REDIS_HOST
        ? {
              url: config.INGESTION_REDIS_HOST,
              options: {
                  port: config.INGESTION_REDIS_PORT,
              },
          }
        : getPosthogRedisConnectionOptions(config)
}

export function getCookielessRedisConnectionOptions(config: CookielessRedisPoolConfig): {
    url: string
    options?: RedisOptions
} {
    return config.COOKIELESS_REDIS_HOST
        ? {
              url: config.COOKIELESS_REDIS_HOST,
              options: {
                  port: config.COOKIELESS_REDIS_PORT ?? 6379,
              },
          }
        : { url: config.REDIS_URL }
}

// Redis client factory (shared implementation)
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

// Type-safe Redis client creators (no casts)
export function createCdpRedis(config: CdpRedisPoolConfig): Promise<Redis.Redis> {
    const { url, options } = getCdpRedisConnectionOptions(config)
    return createRedisClient(url, options)
}

export function createLogsRedis(config: LogsRedisPoolConfig): Promise<Redis.Redis> {
    const { url, options } = getLogsRedisConnectionOptions(config)
    return createRedisClient(url, options)
}

export function createSessionRecordingRedis(config: SessionRecordingRedisConfig): Promise<Redis.Redis> {
    const { url, options } = getSessionRecordingRedisConnectionOptions(config)
    return createRedisClient(url, options)
}

export function createPosthogRedis(config: PosthogRedisPoolConfig): Promise<Redis.Redis> {
    const { url, options } = getPosthogRedisConnectionOptions(config)
    return createRedisClient(url, options)
}

export function createIngestionRedis(config: IngestionRedisPoolConfig): Promise<Redis.Redis> {
    const { url, options } = getIngestionRedisConnectionOptions(config)
    return createRedisClient(url, options)
}

export function createCookielessRedis(config: CookielessRedisPoolConfig): Promise<Redis.Redis> {
    const { url, options } = getCookielessRedisConnectionOptions(config)
    return createRedisClient(url, options)
}

// Type-safe Redis pool creators (no casts)
export function createCdpRedisPool(config: CdpRedisPoolConfig): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createCdpRedis(config),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.REDIS_POOL_MIN_SIZE,
            max: config.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}

export function createLogsRedisPool(config: LogsRedisPoolConfig): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createLogsRedis(config),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.REDIS_POOL_MIN_SIZE,
            max: config.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}

export function createSessionRecordingRedisPool(config: SessionRecordingRedisConfig): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createSessionRecordingRedis(config),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.REDIS_POOL_MIN_SIZE,
            max: config.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}

export function createPosthogRedisPool(config: PosthogRedisPoolConfig): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createPosthogRedis(config),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.REDIS_POOL_MIN_SIZE,
            max: config.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}

export function createIngestionRedisPool(config: IngestionRedisPoolConfig): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createIngestionRedis(config),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.REDIS_POOL_MIN_SIZE,
            max: config.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}

export function createCookielessRedisPool(config: CookielessRedisPoolConfig): RedisPool {
    return createPool<Redis.Redis>(
        {
            create: () => createCookielessRedis(config),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: config.REDIS_POOL_MIN_SIZE,
            max: config.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
}
