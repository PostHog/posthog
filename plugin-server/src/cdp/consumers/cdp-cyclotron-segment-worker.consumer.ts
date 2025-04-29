import { Hub } from '~/src/types'

import { SegmentPluginExecutorService } from '../services/segment-plugin-executor.service'
import { HogFunctionInvocation, HogFunctionInvocationResult, HogFunctionTypeType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of segment plugins.
 */
export class CdpCyclotronWorkerSegment extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerSegment'
    protected queue = 'segment' as const
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private segmentPluginExecutor: SegmentPluginExecutorService

    constructor(hub: Hub) {
        super(hub)
        this.segmentPluginExecutor = new SegmentPluginExecutorService(hub)
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
