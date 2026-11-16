import { createHash } from 'crypto'

import type { CommonConfig } from '~/common/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

// A hung Valkey must not hold the caller's request open.
const VALKEY_TIMEOUT_MS = 1000

export type IdempotencyValkeyConfig = Pick<
    CdpConfig,
    | 'CDP_IDEMPOTENCY_VALKEY_HOST'
    | 'CDP_IDEMPOTENCY_VALKEY_PORT'
    | 'CDP_IDEMPOTENCY_VALKEY_PASSWORD'
    | 'CDP_IDEMPOTENCY_VALKEY_TLS'
> &
    Pick<CommonConfig, 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'>

/**
 * Creates a connection to the workflows Valkey, which holds the daily attachment upload counter. Returns null when
 * the host is unset.
 */
export function createIdempotencyValkeyPool(config: IdempotencyValkeyConfig): RedisV2 | null {
    const name = 'workflows-idempotency'
    if (!config.CDP_IDEMPOTENCY_VALKEY_HOST) {
        logger.info('🔑', `[${name}] no workflows Valkey host configured`)
        return null
    }

    return createRedisV2PoolFromConfig({
        connection: {
            url: config.CDP_IDEMPOTENCY_VALKEY_HOST,
            options: {
                port: config.CDP_IDEMPOTENCY_VALKEY_PORT,
                password: config.CDP_IDEMPOTENCY_VALKEY_PASSWORD,
                tls: config.CDP_IDEMPOTENCY_VALKEY_TLS ? {} : undefined,
                // The caller's timeout only stops the wait. This one aborts the command, so a hung
                // Valkey cannot keep every pool connection borrowed.
                commandTimeout: VALKEY_TIMEOUT_MS,
            },
            name,
            // The counter is optional, so its outage must not stop cdp-api.
            exitOnRepeatedErrors: false,
        },
        // No connection at boot, so cdp-api starts without the counter.
        poolMinSize: 0,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        acquireTimeoutMillis: VALKEY_TIMEOUT_MS,
    })
}

const sortKeys = (value: unknown): unknown => {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeys((value as Record<string, unknown>)[key])])
        )
    }
    return value
}

// Callers may rebuild the same request with its object keys in another order on a retry.
export const requestFingerprint = (request: unknown): string =>
    createHash('sha256')
        .update(JSON.stringify(sortKeys(request)))
        .digest('hex')

export type ReplayFields = Record<string, number>

export type SenderKind = 'email_sandbox'

export type QueuedReply = { replayFields?: ReplayFields; scheduledAt?: string; senderKind?: SenderKind }
