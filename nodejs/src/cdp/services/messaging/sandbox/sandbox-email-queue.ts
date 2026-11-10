import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { RedisPoolConfig } from '~/common/utils/db/redis'
import { PluginsServerConfig } from '~/types'

import { CyclotronJobQueuePostgresV2 } from '../../job-queue/job-queue-postgres-v2'
import {
    CyclotronJobQueueRateLimitedPostgresV2,
    sesRateLimitedQueueOptions,
} from '../../job-queue/job-queue-rate-limited-postgres-v2'
import { CLAIM_DEADLINE_MS, RateLimiterService } from '../../rate-limiter/rate-limiter.service'

export function createSandboxEmailQueue(config: PluginsServerConfig): CyclotronJobQueuePostgresV2 {
    if (!config.SES_RATE_LIMITER_VALKEY_HOST) {
        return new CyclotronJobQueuePostgresV2(config.CONSUMER_BATCH_SIZE, config)
    }
    const sesValkey = createRedisV2PoolFromConfig(sesBucketPoolConfig(config, 'sandbox-email-ses-bucket'))
    return new CyclotronJobQueueRateLimitedPostgresV2(config.CONSUMER_BATCH_SIZE, config, {
        ...sesRateLimitedQueueOptions(config, sesValkey),
        limiter: new RateLimiterService(sesValkey, { name: 'ses', claimDeadlineMs: CLAIM_DEADLINE_MS }),
    })
}

export function sesBucketPoolConfig(
    config: Pick<
        PluginsServerConfig,
        | 'SES_RATE_LIMITER_VALKEY_HOST'
        | 'SES_RATE_LIMITER_VALKEY_PORT'
        | 'SES_RATE_LIMITER_VALKEY_PASSWORD'
        | 'SES_RATE_LIMITER_VALKEY_TLS'
        | 'REDIS_POOL_MIN_SIZE'
        | 'REDIS_POOL_MAX_SIZE'
    >,
    name: string,
    poolMinSize = config.REDIS_POOL_MIN_SIZE
): RedisPoolConfig {
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
