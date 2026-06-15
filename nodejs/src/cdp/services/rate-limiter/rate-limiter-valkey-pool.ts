import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { logger } from '~/utils/logger'

import type { CdpConfig } from '../../config'

export type RateLimiterValkeyConfig = Pick<
    CdpConfig,
    | 'SES_RATE_LIMITER_VALKEY_HOST'
    | 'SES_RATE_LIMITER_VALKEY_PORT'
    | 'SES_RATE_LIMITER_VALKEY_PASSWORD'
    | 'SES_RATE_LIMITER_VALKEY_READER_HOST'
    | 'SES_RATE_LIMITER_VALKEY_READER_PORT'
    | 'SES_RATE_LIMITER_VALKEY_TLS'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
>

export interface RateLimiterValkeyPool {
    writer: RedisV2
    reader: RedisV2
}

/**
 * Creates a connection to the dedicated SES rate-limiter Valkey instance.
 *
 * This is a *primary* store (not a shadow). Provisioned in posthog-cloud-infra
 * as `module "ses_rate_limiter_valkey"`. If you can't set `SES_RATE_LIMITER_VALKEY_HOST`
 * the limiter is disabled and the worker will skip the rate-limit gate entirely
 * (useful for local dev outside k8s; in prod the host is always set).
 *
 * Returns null when the host is unset. Callers should treat this as "rate
 * limiting is disabled in this environment" and proceed without the gate.
 */
export function createSesRateLimiterValkeyPool(
    config: RateLimiterValkeyConfig,
    name = 'ses-rate-limiter'
): RateLimiterValkeyPool | null {
    if (!config.SES_RATE_LIMITER_VALKEY_HOST) {
        logger.info('🪙', `[${name}] no host configured — rate limiter disabled`)
        return null
    }

    logger.info(
        '🪙',
        `[${name}] writer=${config.SES_RATE_LIMITER_VALKEY_HOST}:${config.SES_RATE_LIMITER_VALKEY_PORT} reader=${
            config.SES_RATE_LIMITER_VALKEY_READER_HOST || '<falling back to writer>'
        } tls=${config.SES_RATE_LIMITER_VALKEY_TLS}`
    )

    const tls = config.SES_RATE_LIMITER_VALKEY_TLS ? {} : undefined

    const writer = createRedisV2PoolFromConfig({
        connection: {
            url: config.SES_RATE_LIMITER_VALKEY_HOST,
            options: {
                port: config.SES_RATE_LIMITER_VALKEY_PORT,
                password: config.SES_RATE_LIMITER_VALKEY_PASSWORD,
                tls,
            },
            name,
        },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })

    let reader: RedisV2 = writer
    if (config.SES_RATE_LIMITER_VALKEY_READER_HOST) {
        reader = createRedisV2PoolFromConfig({
            connection: {
                url: config.SES_RATE_LIMITER_VALKEY_READER_HOST,
                options: {
                    port: config.SES_RATE_LIMITER_VALKEY_READER_PORT,
                    password: config.SES_RATE_LIMITER_VALKEY_PASSWORD,
                    tls,
                },
                name: `${name}-reader`,
            },
            poolMinSize: config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        })
    }

    return { writer, reader }
}
