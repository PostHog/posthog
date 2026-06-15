import { PluginsServerConfig } from '~/types'

import { logger } from '../../utils/logger'
import { BatchLimitDecision, JobQueue } from '../services/job-queue/job-queue.interface'
import { createSesRateLimiterValkeyPool } from '../services/rate-limiter/rate-limiter-valkey-pool'
import { RateLimiterService } from '../services/rate-limiter/rate-limiter.service'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

/**
 * The SES sending identity is currently a single global pool, so one bucket
 * key. Switch to per-identity keys when we start sending from multiple SES
 * identities behind this worker.
 */
const SES_BUCKET_KEY = '@posthog/ses/global'

export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'
    private sesRateLimiter: RateLimiterService | null

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'email'

        // Dedicated Valkey instance for SES rate limiting. When host is unset
        // (typical for local dev outside k8s) the limiter is null and dequeue
        // runs unthrottled — fine because local dev won't hit SES.
        const pool = createSesRateLimiterValkeyPool(config)
        this.sesRateLimiter = pool ? new RateLimiterService(pool.writer, { name: 'ses' }) : null
    }

    public override async start(): Promise<void> {
        // Fail-closed on startup: if the rate-limiter Valkey is configured but
        // unreachable, throw and let k8s restart the pod. Sending without the
        // gate would risk getting throttled by SES.
        if (this.sesRateLimiter) {
            await this.sesRateLimiter.ping()
            logger.info('🪙', 'SES rate limiter Valkey connection verified')
        } else {
            logger.warn(
                '🪙',
                'SES rate limiter not configured (SES_RATE_LIMITER_VALKEY_HOST unset) — dequeue is not throttled'
            )
        }
        await super.start()
    }

    /**
     * Claim outbound SES capacity before dequeuing. The worker only pulls as
     * many jobs as we have tokens for — when the bucket is empty we don't
     * touch Postgres at all, avoiding the dequeue-and-reschedule churn that
     * would otherwise dominate when SES is the bottleneck.
     *
     * Runtime Valkey errors return 0 granted (fail-closed mid-shift). Pod
     * sleeps for the throttled poll delay and tries again.
     */
    protected override async getBatchLimit(): Promise<BatchLimitDecision | undefined> {
        if (!this.sesRateLimiter) {
            return undefined
        }
        const granted = await this.sesRateLimiter.claimUpTo({
            key: SES_BUCKET_KEY,
            requested: this.config.CDP_SES_RATE_LIMIT_CAPACITY,
            capacity: this.config.CDP_SES_RATE_LIMIT_CAPACITY,
            refillPerSecond: this.config.CDP_SES_RATE_LIMIT_REFILL_PER_SECOND,
        })
        if (granted === 0) {
            return { limit: 0, sleepMs: this.config.CDP_SES_RATE_LIMIT_THROTTLED_POLL_DELAY_MS }
        }
        return { limit: granted }
    }
}
