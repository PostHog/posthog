import type { CommonConfig } from '~/common/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

export type FrequencyCapValkeyConfig = Pick<
    CdpConfig,
    | 'CDP_FREQUENCY_CAP_VALKEY_HOST'
    | 'CDP_FREQUENCY_CAP_VALKEY_PORT'
    | 'CDP_FREQUENCY_CAP_VALKEY_PASSWORD'
    | 'CDP_FREQUENCY_CAP_VALKEY_TLS'
> &
    Pick<CommonConfig, 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'>

/**
 * Creates a connection to the dedicated frequency cap Valkey instance. Returns null when the host
 * is unset, and the frequency cap is then off in that environment.
 */
export function createFrequencyCapValkeyPool(config: FrequencyCapValkeyConfig): RedisV2 | null {
    const name = 'workflows-frequency-cap'
    if (!config.CDP_FREQUENCY_CAP_VALKEY_HOST) {
        logger.info('🧢', `[${name}] no frequency cap Valkey host configured — frequency cap disabled`)
        return null
    }

    logger.info(
        '🧢',
        `[${name}] writer=${config.CDP_FREQUENCY_CAP_VALKEY_HOST}:${config.CDP_FREQUENCY_CAP_VALKEY_PORT} tls=${config.CDP_FREQUENCY_CAP_VALKEY_TLS}`
    )

    return createRedisV2PoolFromConfig({
        connection: {
            url: config.CDP_FREQUENCY_CAP_VALKEY_HOST,
            options: {
                port: config.CDP_FREQUENCY_CAP_VALKEY_PORT,
                password: config.CDP_FREQUENCY_CAP_VALKEY_PASSWORD,
                tls: config.CDP_FREQUENCY_CAP_VALKEY_TLS ? {} : undefined,
            },
            name,
        },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })
}
