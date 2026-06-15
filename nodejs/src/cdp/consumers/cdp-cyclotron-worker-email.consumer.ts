import { PluginsServerConfig } from '~/types'

import { logger } from '../../utils/logger'
import { CyclotronV2BatchLimit } from '../services/cyclotron-v2'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { RateLimitedJobQueue } from '../services/job-queue/job-queue-rate-limited'
import { JobQueue } from '../services/job-queue/job-queue.interface'
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

        const valkey = createSesRateLimiterValkeyPool(config)
        this.sesRateLimiter = valkey ? new RateLimiterService(valkey, { name: 'ses' }) : null

        if (this.sesRateLimiter) {
            if (!(jobQueue instanceof CyclotronJobQueuePostgresV2)) {
                throw new Error(
                    'CdpCyclotronWorkerEmail with SES rate limiting requires the Postgres-V2 job queue backend (dynamic batch sizing is not supported on Kafka).'
                )
            }
            // Wrap the raw queue with the rate-limit decorator. The parent's
            // `start()` calls cyclotronJobQueue.startAsConsumer(...), which the
            // decorator intercepts to install the hook before delegating.
            this.cyclotronJobQueue = new RateLimitedJobQueue(jobQueue, () => this.claimSesTokens())
        }
    }

    public override async start(): Promise<void> {
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
    private async claimSesTokens(): Promise<CyclotronV2BatchLimit | undefined> {
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
