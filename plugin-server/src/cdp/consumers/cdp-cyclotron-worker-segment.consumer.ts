import { Hub } from '~/types'

import { SegmentDestinationExecutorService } from '../services/segment-destination-executor.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of segment plugins.
 */
export class CdpCyclotronWorkerSegment extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerSegment'
    private segmentPluginExecutor: SegmentDestinationExecutorService

    constructor(hub: Hub) {
        super(hub, 'segment')
        this.segmentPluginExecutor = new SegmentDestinationExecutorService(this.hub)
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        // Segment plugins fire fetch requests and so need to be run in true parallel
        const loadedInvocations = await this.loadHogFunctions(invocations)

        return await Promise.all(
            loadedInvocations.map((item) =>
                this.runInstrumented(
                    'handleEachBatch.executePluginInvocation',
                    async () => await this.segmentPluginExecutor.execute(item)
                )
            )
        )
    }
}
