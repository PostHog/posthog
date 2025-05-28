import { Hub } from '~/src/types'

import { SegmentDestinationExecutorService } from '../services/segment-destination-executor.service'
import { HogFunctionInvocation, HogFunctionInvocationResult, HogFunctionTypeType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of segment plugins.
 */
export class CdpCyclotronWorkerSegment extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerSegment'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private segmentPluginExecutor: SegmentDestinationExecutorService

    constructor(hub: Hub) {
        super(hub, 'segment')
        this.segmentPluginExecutor = new SegmentDestinationExecutorService()
    }

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        // Segment plugins fire fetch requests and so need to be run in true parallel
        return await Promise.all(
            invocations.map((item) =>
                this.runInstrumented(
                    'handleEachBatch.executePluginInvocation',
                    async () => await this.segmentPluginExecutor.execute(item)
                )
            )
        )
    }
}
