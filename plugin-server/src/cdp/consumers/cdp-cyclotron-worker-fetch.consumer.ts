import { Hub } from '../../types'
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
        return (await this.runManyWithHeartbeat(invocations, (x) => this.fetchExecutor.execute(x))).filter(filterExists)
    }
}
