import { Hub } from '../../types'
import { FetchExecutorService } from '../services/fetch-executor.service'
import { HogFunctionInvocation, HogFunctionInvocationResult } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

// Mostly used for testing the fetch executor
export class CdpCyclotronWorkerFetch extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerFetch'
    protected queue = 'fetch' as const

    private fetchExecutor: FetchExecutorService

    constructor(hub: Hub) {
        super(hub)
        this.fetchExecutor = new FetchExecutorService(this.hub)
    }

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        // NOTE: this service will never do fetching (unless we decide we want to do it in node at some point, its only used for e2e testing)
        return (await this.runManyWithHeartbeat(invocations, (item) => this.fetchExecutor.execute(item))).filter(
            Boolean
        ) as HogFunctionInvocationResult[]
    }
}
