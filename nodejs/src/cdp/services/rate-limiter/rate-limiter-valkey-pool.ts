import type { CommonConfig } from '~/common/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

const OPTIONAL_VALKEY_TIMEOUT_MS = 250

export type RateLimiterValkeyConfig = Pick<
    CdpConfig,
    | 'SES_RATE_LIMITER_VALKEY_HOST'
    | 'SES_RATE_LIMITER_VALKEY_PORT'
    | 'SES_RATE_LIMITER_VALKEY_PASSWORD'
    | 'SES_RATE_LIMITER_VALKEY_TLS'
> &
    Pick<CommonConfig, 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'>

/**
 * Creates a connection to the dedicated SES Valkey instance, shared by the
 * SES rate limiter and the email MX-validation cache (each caller gets its
 * own pool via `name`).
 *
 * Single writer pool — the rate limiter's Lua script only writes (hset +
 * expire) and the MX cache is low-volume, so there's no use for a read-only
 * replica. Returns null when the host is unset (local dev outside k8s);
 * callers treat that as "feature disabled in this environment" and proceed
 * without it.
 */
export function createSesRateLimiterValkeyPool(
    config: RateLimiterValkeyConfig,
    name = 'ses-rate-limiter',
    { optional = false, failFast = false }: { optional?: boolean; failFast?: boolean } = {}
): RedisV2 | null {
    if (!config.SES_RATE_LIMITER_VALKEY_HOST) {
        logger.info('🪙', `[${name}] no SES Valkey host configured — feature disabled`)
        return null
    }

    logger.info(
        '🪙',
        `[${name}] writer=${config.SES_RATE_LIMITER_VALKEY_HOST}:${config.SES_RATE_LIMITER_VALKEY_PORT} tls=${config.SES_RATE_LIMITER_VALKEY_TLS}`
    )

    const tls = config.SES_RATE_LIMITER_VALKEY_TLS ? {} : undefined

    // A caller that works without this Valkey must not stop when it is down, or wait on it long.
    const pool = createRedisV2PoolFromConfig({
        connection: {
            url: config.SES_RATE_LIMITER_VALKEY_HOST,
            options: {
                port: config.SES_RATE_LIMITER_VALKEY_PORT,
                password: config.SES_RATE_LIMITER_VALKEY_PASSWORD,
                tls,
                ...(optional ? { commandTimeout: OPTIONAL_VALKEY_TIMEOUT_MS } : {}),
            },
            name,
            exitOnRepeatedErrors: !optional,
        },
        poolMinSize: optional ? 0 : config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        ...(optional ? { acquireTimeoutMillis: OPTIONAL_VALKEY_TIMEOUT_MS } : {}),
    })
    return failFast ? withoutOfflineQueue(pool) : pool
}

// The sandbox daily caps run inside a send, so they always use a bounded pool: a stalled Valkey fails the
// check instead of holding the worker's whole batch.
export function createSandboxEmailCapValkeyPool(config: RateLimiterValkeyConfig): RedisV2 | null {
    return createSesRateLimiterValkeyPool(config, 'sandbox-email-cap', { optional: true, failFast: true })
}

// A client waits for its first connection in the offline queue, so the queue can only be switched off
// once the pool hands the client out. After that a dropped connection fails commands at once instead of
// queueing every caller's work for the whole outage and replaying it on recovery.
function withoutOfflineQueue(pool: RedisV2): RedisV2 {
    const useClient: RedisV2['useClient'] = (options, callback) =>
        pool.useClient(options, (client) => {
            client.options.enableOfflineQueue = false
            return callback(client)
        })
    return {
        useClient,
        usePipeline: (options, callback) =>
            useClient(options, async (client) => {
                const pipeline = client.pipeline()
                callback(pipeline)
                return pipeline.exec()
            }),
    }
}
