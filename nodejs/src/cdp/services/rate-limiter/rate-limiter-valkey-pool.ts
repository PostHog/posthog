import type { CommonConfig } from '~/common/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

export type RateLimiterValkeyConfig = Pick<
    CdpConfig,
    | 'SES_RATE_LIMITER_VALKEY_HOST'
    | 'SES_RATE_LIMITER_VALKEY_PORT'
    | 'SES_RATE_LIMITER_VALKEY_PASSWORD'
    | 'SES_RATE_LIMITER_VALKEY_TLS'
> &
    Pick<CommonConfig, 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'>

/**
 * Creates a connection to the dedicated SES rate-limiter Valkey instance.
 *
 * Single writer pool — every operation in the rate limiter's Lua script is a
 * write (hset + expire), so there's no use for a read-only replica. Returns
 * null when the host is unset (local dev outside k8s); callers treat that as
 * "rate limiting disabled in this environment" and proceed without the gate.
 */
export function createSesRateLimiterValkeyPool(
    config: RateLimiterValkeyConfig,
    name = 'ses-rate-limiter'
): RedisV2 | null {
    if (!config.SES_RATE_LIMITER_VALKEY_HOST) {
        logger.info('🪙', `[${name}] no host configured — rate limiter disabled`)
        return null
    }

    logger.info(
        '🪙',
        `[${name}] writer=${config.SES_RATE_LIMITER_VALKEY_HOST}:${config.SES_RATE_LIMITER_VALKEY_PORT} tls=${config.SES_RATE_LIMITER_VALKEY_TLS}`
    )

    const tls = config.SES_RATE_LIMITER_VALKEY_TLS ? {} : undefined

    return createRedisV2PoolFromConfig({
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
}
