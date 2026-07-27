import { CyclotronJobInvocation, CyclotronJobQueueKind } from '../../types'
import { CyclotronV2BatchLimit, CyclotronV2RateLimitedWorker, CyclotronV2Worker } from '../cyclotron-v2'
import { CyclotronV2WorkerConfig } from '../cyclotron-v2/types'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { CyclotronJobQueuePostgresV2 } from './job-queue-postgres-v2'

export interface RateLimitedQueueOptions {
    limiter: RateLimiterService
    /** Token-bucket key, e.g. `@posthog/ses/global`. */
    key: string
    /** Bucket capacity (burst size). */
    capacity: number
    /** Tokens added per second. */
    refillPerSecond: number
    /** How long to sleep when the bucket is empty before re-checking. */
    throttledPollDelayMs: number
}

/**
 * Postgres-V2 job queue variant that gates dequeue behind a distributed token
 * bucket. Used by the email worker to claim SES capacity before pulling jobs.
 *
 * The base queue and `CyclotronV2Worker` are completely untouched — other
 * consumers (hog, hogflow, etc.) construct the base queue and never load the
 * rate-limit code path.
 */
export class CyclotronJobQueueRateLimitedPostgresV2 extends CyclotronJobQueuePostgresV2 {
    constructor(
        consumerBatchSize: number,
        config: ConstructorParameters<typeof CyclotronJobQueuePostgresV2>[1],
        private rateLimit: RateLimitedQueueOptions
    ) {
        super(consumerBatchSize, config)
    }

    public override async startAsConsumer(
        queue: CyclotronJobQueueKind,
        consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ): Promise<void> {
        // Fail-closed on startup: unreachable Valkey throws and lets k8s
        // restart the pod. Sending without the gate would risk SES reputation
        // damage, so we don't start the consumer until the limiter is healthy.
        await this.rateLimit.limiter.ping()

        await super.startAsConsumer(queue, consumeBatch)
    }

    protected override createWorker(workerConfig: CyclotronV2WorkerConfig): CyclotronV2Worker {
        return new CyclotronV2RateLimitedWorker(workerConfig, (requested) => this.claimBatchLimit(requested))
    }

    /**
     * Claim outbound capacity from the bucket before each poll. `requested` is
     * the number of rows the worker actually sees as dequeueable right now
     * (capped at batchMaxSize). We additionally cap it at bucket capacity, in
     * case capacity < batchMaxSize. Returns the decision the worker applies:
     * how many rows to dequeue, or "skip and sleep" when nothing was granted.
     * Runtime Valkey errors return 0 granted (fail-closed mid-shift) — the
     * worker sleeps and retries.
     *
     * Pre-sizing `requested` to the visible row count is what fixes the
     * "sparse traffic drains the bucket" failure mode: if only one row is
     * ready we ask for one token, not `capacity`. Granted tokens above the
     * row count would otherwise be deducted from the bucket but never used
     * (the worker's `effectiveLimit` is `min(decision.limit, batchMaxSize)`).
     */
    private async claimBatchLimit(requested: number): Promise<CyclotronV2BatchLimit | undefined> {
        const claimRequested = Math.min(requested, this.rateLimit.capacity)
        const granted = await this.rateLimit.limiter.claimUpTo({
            key: this.rateLimit.key,
            requested: claimRequested,
            capacity: this.rateLimit.capacity,
            refillPerSecond: this.rateLimit.refillPerSecond,
        })
        if (granted === 0) {
            return { limit: 0, sleepMs: this.rateLimit.throttledPollDelayMs }
        }
        return { limit: granted }
    }
}
