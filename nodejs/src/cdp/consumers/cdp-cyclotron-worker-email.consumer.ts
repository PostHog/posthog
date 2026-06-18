import { Counter } from 'prom-client'

import { PluginsServerConfig } from '~/types'

import { logger } from '../../utils/logger'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

const emailServicePromotedCounter = new Counter({
    name: 'cdp_cyclotron_v2_email_service_promoted',
    help: 'Email rows promoted to fair-dequeueable by the email consumer fallback pass (janitor is primary)',
})

/**
 * Fallback cadence for the scheduled→dequeueable promotion. Janitor runs at
 * ~10s with a ~10k batch and handles the bulk of promotions; this consumer
 * runs at 60s with a 1k batch so the fallback can genuinely stand in for the
 * janitor at moderate volume (~16 rows/sec/pod) instead of just papering over
 * second-scale restarts. If both are healthy this almost always promotes 0
 * rows because the janitor already swept them.
 */
const PROMOTION_INTERVAL_MS = 60_000
const PROMOTION_BATCH_SIZE = 1_000

export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'

    private promotionIntervalHandle: ReturnType<typeof setInterval> | null = null

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'email'
    }

    public override async start(): Promise<void> {
        await super.start()
        this.promotionIntervalHandle = setInterval(() => {
            this.runPromotionPass().catch((err) => {
                // Non-fatal — the janitor's pass is the primary mechanism.
                logger.warn('CdpCyclotronWorkerEmail promotion pass failed', { error: String(err) })
            })
        }, PROMOTION_INTERVAL_MS)
    }

    public override async stop(): Promise<void> {
        if (this.promotionIntervalHandle) {
            clearInterval(this.promotionIntervalHandle)
            this.promotionIntervalHandle = null
        }
        await super.stop()
    }

    private async runPromotionPass(): Promise<void> {
        if (!this.cyclotronJobQueue.runScheduledPromotion) {
            return
        }
        const promoted = await this.cyclotronJobQueue.runScheduledPromotion(PROMOTION_BATCH_SIZE)
        if (promoted > 0) {
            emailServicePromotedCounter.inc(promoted)
            logger.info('CdpCyclotronWorkerEmail promoted scheduled email jobs', { count: promoted })
        }
    }
}
