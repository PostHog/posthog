import { PluginsServerConfig } from '~/types'

import { CyclotronJobQueueRateLimitedPostgresV2 } from '../services/job-queue/job-queue-rate-limited-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { createSesRateLimiterValkeyPool } from '../services/rate-limiter/rate-limiter-valkey-pool'
import { RateLimiterService } from '../services/rate-limiter/rate-limiter.service'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow, routeBackToHogFlowQueue } from './cdp-cyclotron-worker-hogflow.consumer'

export const CLASSIFY_GLOBAL_BUCKET_KEY = '@posthog/classify/global'

/**
 * Runs the "Classify with AI" step of workflow runs. The hogflow worker moves each classification here, and this
 * worker makes the call and sends the run back. One dequeued job makes at most one call, so the token bucket of its
 * queue limits the calls a second however many runs wait.
 */
export class CdpCyclotronWorkerClassify extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerClassify'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'classify'
    }

    // A step can also end here, such as when the call cannot be made, and the rest of the run must not stay behind.
    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const results = await super.processInvocations(invocations)
        return results.map((result) =>
            !result.finished &&
            result.invocation.queue === 'classify' &&
            result.invocation.queueParameters?.type !== 'classify'
                ? routeBackToHogFlowQueue(result as CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>)
                : result
        )
    }
}

/**
 * Unlike the email worker, the classify worker has no unthrottled fallback: without the limiter's Valkey it would
 * send the model every waiting classification at once, so it refuses to start instead.
 */
export function createClassifyJobQueue(config: PluginsServerConfig): CyclotronJobQueueRateLimitedPostgresV2 {
    const limiterValkey = createSesRateLimiterValkeyPool(config, 'classify-rate-limiter')
    if (!limiterValkey) {
        throw new Error(
            'The classify worker needs SES_RATE_LIMITER_VALKEY_HOST for its rate limit, so it refuses to start without it.'
        )
    }
    return new CyclotronJobQueueRateLimitedPostgresV2(config.CONSUMER_BATCH_SIZE, config, {
        limiter: new RateLimiterService(limiterValkey, { name: 'classify' }),
        key: CLASSIFY_GLOBAL_BUCKET_KEY,
        capacity: config.CDP_CLASSIFY_RATE_LIMIT_CAPACITY,
        refillPerSecond: config.CDP_CLASSIFY_RATE_LIMIT_REFILL_PER_SECOND,
        throttledPollDelayMs: config.CDP_CLASSIFY_RATE_LIMIT_THROTTLED_POLL_DELAY_MS,
    })
}
