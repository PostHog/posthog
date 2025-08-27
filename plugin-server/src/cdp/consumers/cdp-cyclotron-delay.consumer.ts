import { Hub } from '../../types'
import { HogDelayService } from '../services/hog-delay.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * Consumer for delayed invocations
 */
export class CdpCyclotronDelayConsumer extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronDelayConsumer'
    private hogDelayService: HogDelayService

    constructor(hub: Hub) {
        super(hub, 'delay_24h')
        this.hogDelayService = new HogDelayService(24 * 60 * 60 * 1000) // 24 hours
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        return await this.hogDelayService.processBatchWithDelay(invocations)
    }
}
