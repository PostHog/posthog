import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { FetchExecutorService } from '../services/fetch-executor.service'
import { HogFunctionInvocation, HogFunctionInvocationResult } from '../types'
import { filterExists } from '../utils'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

export class CdpCyclotronWorkerFetch extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerFetch'
    private fetchExecutor: FetchExecutorService

    constructor(hub: Hub) {
        super(hub, 'fetch')
        this.fetchExecutor = new FetchExecutorService(this.hub)
    }

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        // Plugins fire fetch requests and so need to be run in true parallel
        logger.info(`Processing ${invocations.length} fetch invocations`)
        return (
            await Promise.all(
                invocations.map((item) =>
                    this.runInstrumented(
                        'handleEachBatch.executeFetchInvocation',
                        async () => await this.fetchExecutor.execute(item)
                    )
                )
            )
        ).filter(filterExists)
    }
}
