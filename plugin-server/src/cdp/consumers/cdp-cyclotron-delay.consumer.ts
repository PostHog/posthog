import { Hub } from '../../types'
import { HogDelayService } from '../services/hog-delay.service'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { logger } from '~/utils/logger'

/**
 * Consumer for delayed invocations
 */
export class CdpCyclotronDelayConsumer extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronDelayConsumer'
    private hogDelayService: HogDelayService

    constructor(hub: Hub) {
        super(hub, 'delay_10m')
        this.hogDelayService = new HogDelayService(10 * 60 * 1000) // 10 minutes

        this.cyclotronJobQueue = new CyclotronJobQueue(hub, this.queue, (batch) => this.processBatch(batch), 'delay')
    }

    public async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        logger.info('🔁', `${this.name} - handling batch`, {
            size: invocations.length,
        })

        return { backgroundTask: Promise.resolve(), invocationResults: [] }
    }
}
