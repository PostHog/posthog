import { Hub } from '../../types'
import { LegacyPluginExecutorService } from '../services/legacy-plugin-executor.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, HogFunctionTypeType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of legacy plugins.
 */
export class CdpCyclotronWorkerPlugins extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerPlugins'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private pluginExecutor: LegacyPluginExecutorService

    constructor(hub: Hub) {
        super(hub, 'plugin')
        this.pluginExecutor = new LegacyPluginExecutorService(hub)
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        const loadedInvocations = await this.loadHogFunctions(invocations)
        // Plugins fire fetch requests and so need to be run in true parallel
        return await Promise.all(
            loadedInvocations.map((item) =>
                this.runInstrumented(
                    'handleEachBatch.executePluginInvocation',
                    async () => await this.pluginExecutor.execute(item)
                )
            )
        )
    }
}
