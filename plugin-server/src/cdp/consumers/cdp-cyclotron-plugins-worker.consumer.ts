import { Hub } from '~/src/types'

import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { HogFunctionInvocation, HogFunctionInvocationResult, HogFunctionTypeType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */
export class CdpCyclotronWorkerPlugins extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerPlugins'
    protected queue = 'plugin' as const
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private pluginExecutor: LegacyPluginExecutorService

    constructor(hub: Hub) {
        super(hub)
        this.pluginExecutor = new LegacyPluginExecutorService()
    }

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        return await this.runManyWithHeartbeat(invocations, (item) => this.pluginExecutor.execute(item))
    }
}
