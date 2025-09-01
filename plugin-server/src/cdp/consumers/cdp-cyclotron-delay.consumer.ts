import { logger } from '~/utils/logger'

import { Hub } from '../../types'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * Consumer for delayed invocations
 */
export class CdpCyclotronDelayConsumer extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronDelayConsumer'

    constructor(hub: Hub) {
        super(hub, 'delay_10m') // TODO: make the queue configurable via an env variable
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
