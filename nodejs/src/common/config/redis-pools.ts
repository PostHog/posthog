import { CommonConfig } from '~/common/config'

import { RedisConnectionConfig } from '../utils/db/redis'

/**
 * Build the connection config for the ingestion Redis pool.
 * Fallback chain: INGESTION_REDIS_HOST → POSTHOG_REDIS_HOST → REDIS_URL
 */
export function createIngestionRedisConnectionConfig(
    config: Pick<
        CommonConfig,
        | 'INGESTION_REDIS_HOST'
        | 'INGESTION_REDIS_PORT'
        | 'POSTHOG_REDIS_HOST'
        | 'POSTHOG_REDIS_PORT'
        | 'POSTHOG_REDIS_PASSWORD'
        | 'REDIS_URL'
    >
): RedisConnectionConfig {
    if (config.INGESTION_REDIS_HOST) {
        return {
            url: config.INGESTION_REDIS_HOST,
            options: { port: config.INGESTION_REDIS_PORT },
            name: 'ingestion-redis',
        }
    }
    if (config.POSTHOG_REDIS_HOST) {
        return {
            url: config.POSTHOG_REDIS_HOST,
            options: { port: config.POSTHOG_REDIS_PORT, password: config.POSTHOG_REDIS_PASSWORD },
            name: 'ingestion-redis',
        }
    }
    return { url: config.REDIS_URL, name: 'ingestion-redis' }
}

/**
 * Build the connection config for the PostHog Redis pool.
 * Fallback chain: POSTHOG_REDIS_HOST → REDIS_URL
 */
export function createPosthogRedisConnectionConfig(
    config: Pick<CommonConfig, 'POSTHOG_REDIS_HOST' | 'POSTHOG_REDIS_PORT' | 'POSTHOG_REDIS_PASSWORD' | 'REDIS_URL'>
): RedisConnectionConfig {
    if (config.POSTHOG_REDIS_HOST) {
        return {
            url: config.POSTHOG_REDIS_HOST,
            options: { port: config.POSTHOG_REDIS_PORT, password: config.POSTHOG_REDIS_PASSWORD },
            name: 'posthog-redis',
        }
    }
    return { url: config.REDIS_URL, name: 'posthog-redis' }
}

/** Cookieless Redis connection params — COOKIELESS_REDIS_* are ingestion-specific config keys. */
export type CookielessRedisConfig = {
    COOKIELESS_REDIS_HOST: string
    COOKIELESS_REDIS_PORT: number
}

/** $feature_flag_called dedup Redis connection params — these are ingestion-specific config keys. */
export type FeatureFlagCalledDedupRedisConfig = {
    INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_HOST: string
    INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_PORT: number
}

/**
 * Build the connection config for the $feature_flag_called dedup Redis pool.
 *
 * Falls back to the ingestion Redis connection (not REDIS_URL) when no dedicated
 * host is set, so dedup claims keep landing on the instance they use today until
 * INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_HOST points at the dedicated instance.
 */
export function createFeatureFlagCalledDedupRedisConnectionConfig(
    config: FeatureFlagCalledDedupRedisConfig &
        Pick<
            CommonConfig,
            | 'INGESTION_REDIS_HOST'
            | 'INGESTION_REDIS_PORT'
            | 'POSTHOG_REDIS_HOST'
            | 'POSTHOG_REDIS_PORT'
            | 'POSTHOG_REDIS_PASSWORD'
            | 'REDIS_URL'
        >
): RedisConnectionConfig {
    if (config.INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_HOST) {
        return {
            url: config.INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_HOST,
            options: { port: config.INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_PORT ?? 6379 },
            name: 'ff-called-dedup-redis',
        }
    }
    return { ...createIngestionRedisConnectionConfig(config), name: 'ff-called-dedup-redis' }
}

/**
 * Build the connection config for the cookieless Redis pool.
 * Fallback chain: COOKIELESS_REDIS_HOST → REDIS_URL
 */
export function createCookielessRedisConnectionConfig(
    config: CookielessRedisConfig & Pick<CommonConfig, 'REDIS_URL'>
): RedisConnectionConfig {
    if (config.COOKIELESS_REDIS_HOST) {
        return {
            url: config.COOKIELESS_REDIS_HOST,
            options: { port: config.COOKIELESS_REDIS_PORT ?? 6379 },
            name: 'cookieless-redis',
        }
    }
    return { url: config.REDIS_URL, name: 'cookieless-redis' }
}
