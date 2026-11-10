import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
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
    const sesValkey = createRedisV2PoolFromConfig({
        connection: {
            url: config.SES_RATE_LIMITER_VALKEY_HOST,
            options: {
                port: config.SES_RATE_LIMITER_VALKEY_PORT,
                password: config.SES_RATE_LIMITER_VALKEY_PASSWORD,
                tls: config.SES_RATE_LIMITER_VALKEY_TLS ? {} : undefined,
            },
            name: 'sandbox-email-ses-bucket',
            exitOnRepeatedErrors: false,
        },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
    })
    return new CyclotronJobQueueRateLimitedPostgresV2(config.CONSUMER_BATCH_SIZE, config, {
        ...sesRateLimitedQueueOptions(config, sesValkey),
        limiter: new RateLimiterService(sesValkey, { name: 'ses', claimDeadlineMs: CLAIM_DEADLINE_MS }),
    })
}
