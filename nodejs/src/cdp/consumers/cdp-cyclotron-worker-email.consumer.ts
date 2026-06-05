import { PluginsServerConfig } from '~/types'

import { ConsumerOptions, JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

/**
 * Dedicated email worker that paces sends to AWS SES's per-second rate cap.
 *
 * The effective rate is `CDP_EMAIL_BATCH_SIZE × 1000 / CDP_EMAIL_MIN_BATCH_INTERVAL_MS`
 * sends/sec. Two values rather than a derived "rate" knob so operators can
 * tune smoothness (small batch + short interval = smoother) independently of
 * total throughput.
 *
 * The min-batch-interval guarantee is enforced here, not by cyclotron-v2's
 * `pollDelayMs` — that only paces the empty-queue backoff, so a full queue
 * + fast SES would let the loop run as fast as HTTP allowed. We hold each
 * tick open via setTimeout so the next dequeue can't start until the
 * interval has elapsed.
 *
 * Expected to run as a single replica (deployment `replicas: 1`,
 * `strategy: Recreate`) — distributed coordination is intentionally absent.
 * On pod crash, jobs sit `available` in postgres until k8s reschedules.
 */
export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'email'
    }

    protected override getConsumerOptions(): ConsumerOptions {
        return {
            batchMaxSize: this.config.CDP_EMAIL_BATCH_SIZE,
            pollDelayMs: this.config.CDP_EMAIL_MIN_BATCH_INTERVAL_MS,
        }
    }

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const start = Date.now()
        const result = await super.processInvocations(invocations)

        // Hold the tick open so the v2 worker can't immediately re-poll on a
        // non-empty queue. Without this, fast SES responses + a backed-up queue
        // would dispatch as fast as the HTTP latency allowed, blowing past the
        // configured rate.
        const elapsed = Date.now() - start
        const remaining = this.config.CDP_EMAIL_MIN_BATCH_INTERVAL_MS - elapsed
        if (remaining > 0) {
            await new Promise((r) => setTimeout(r, remaining))
        }

        return result
    }
}
