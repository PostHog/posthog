import { isCloud } from '~/utils/env-utils'
import { logger } from '~/utils/logger'

import { HealthCheckResult, Hub } from '../../types'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { CyclotronJobInvocation, CyclotronJobQueueKind } from '../types'
import { CdpConsumerBase } from './cdp-base.consumer'

/**
 * Consumer for delayed invocations
 */
export class CdpCyclotronDelayConsumer extends CdpConsumerBase {
    protected name = 'CdpCyclotronDelayConsumer'
    protected cyclotronJobQueue: CyclotronJobQueue
    protected queue: CyclotronJobQueueKind

    constructor(hub: Hub) {
        super(hub)
        this.queue = !isCloud() ? 'delay10m' : hub.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND

        if (!['delay10m', 'delay60m', 'delay24h'].includes(this.queue)) {
            throw new Error(`Invalid cyclotron job queue kind: ${this.queue}`)
        }

        this.cyclotronJobQueue = new CyclotronJobQueue(hub, this.queue, (batch) => this.processBatch(batch), 'delay')
    }

    // eslint-disable-next-line @typescript-eslint/require-await
    public async processBatch(invocations: CyclotronJobInvocation[]): Promise<{ backgroundTask: Promise<any> }> {
        logger.info('🔁', `${this.name} - handling batch`, {
            size: invocations.length,
        })

        return { backgroundTask: Promise.resolve() }
    }

    public async start() {
        await super.start()
        await this.cyclotronJobQueue.start()
    }

    public async stop() {
        logger.info('🔄', 'Stopping cyclotron delay consumer')
        await this.cyclotronJobQueue.stop()

        // IMPORTANT: super always comes last
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.cyclotronJobQueue.isHealthy()
    }
}
