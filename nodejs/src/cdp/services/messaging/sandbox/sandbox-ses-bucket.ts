import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { RedisPoolConfig } from '~/common/utils/db/redis'
import { PluginsServerConfig } from '~/types'

import { RateLimitedQueueOptions, sesRateLimitedQueueOptions } from '../../job-queue/job-queue-rate-limited-postgres-v2'
import { OPTIONAL_VALKEY_TIMEOUT_MS } from '../../rate-limiter/rate-limiter-valkey-pool'
import { CLAIM_DEADLINE_MS, RateLimiterService } from '../../rate-limiter/rate-limiter.service'

export type SandboxSesBucket = Pick<RateLimitedQueueOptions, 'limiter' | 'key' | 'capacity' | 'refillPerSecond'>

type SesBucketConfig = Pick<
    PluginsServerConfig,
    | 'SES_RATE_LIMITER_VALKEY_HOST'
    | 'SES_RATE_LIMITER_VALKEY_PORT'
    | 'SES_RATE_LIMITER_VALKEY_PASSWORD'
    | 'SES_RATE_LIMITER_VALKEY_TLS'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
    | 'CDP_SES_RATE_LIMIT_CAPACITY'
    | 'CDP_SES_RATE_LIMIT_REFILL_PER_SECOND'
    | 'CDP_SES_RATE_LIMIT_THROTTLED_POLL_DELAY_MS'
>

export function sandboxWorkerSesBucket(config: SesBucketConfig): SandboxSesBucket {
    return createSesBucket(config, 'sandbox-email-ses-bucket', CLAIM_DEADLINE_MS, config.REDIS_POOL_MIN_SIZE)
}

export function sandboxTestSendBucket(config: SesBucketConfig): SandboxSesBucket | null {
    if (!config.SES_RATE_LIMITER_VALKEY_HOST) {
        return null
    }
    return createSesBucket(config, 'sandbox-email-test-send', OPTIONAL_VALKEY_TIMEOUT_MS, 0)
}

export async function claimSesSlot({ limiter, key, capacity, refillPerSecond }: SandboxSesBucket): Promise<boolean> {
    return (await limiter.claimUpTo({ key, requested: 1, capacity, refillPerSecond })) >= 1
}

function createSesBucket(
    config: SesBucketConfig,
    name: string,
    claimDeadlineMs: number,
    poolMinSize: number
): SandboxSesBucket {
    const valkey = createRedisV2PoolFromConfig(sesBucketPoolConfig(config, name, poolMinSize))
    return {
        ...sesRateLimitedQueueOptions(config, valkey),
        limiter: new RateLimiterService(valkey, { name: 'ses', claimDeadlineMs }),
    }
}

function sesBucketPoolConfig(config: SesBucketConfig, name: string, poolMinSize: number): RedisPoolConfig {
    return {
        connection: {
            url: config.SES_RATE_LIMITER_VALKEY_HOST,
            options: {
                port: config.SES_RATE_LIMITER_VALKEY_PORT,
                password: config.SES_RATE_LIMITER_VALKEY_PASSWORD,
                tls: config.SES_RATE_LIMITER_VALKEY_TLS ? {} : undefined,
            },
            name,
            exitOnRepeatedErrors: false,
        },
        poolMinSize,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    }
}
