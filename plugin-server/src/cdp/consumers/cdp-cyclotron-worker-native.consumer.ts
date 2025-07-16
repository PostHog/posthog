import { Hub } from '~/types'

import { NativeDestinationExecutorService } from '../services/native-destination-executor.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

/**
 * NOTE: This is a consumer to take care of native plugins.
 */
export class CdpCyclotronWorkerNative extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerNative'
    private nativePluginExecutor: NativeDestinationExecutorService

    constructor(hub: Hub) {
        super(hub, 'native')
        this.nativePluginExecutor = new NativeDestinationExecutorService(this.hub)
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        // native plugins fire fetch requests and so need to be run in true parallel
        const loadedInvocations = await this.loadHogFunctions(invocations)

        return await Promise.all(
            loadedInvocations.map((item) =>
                this.runInstrumented(
                    'handleEachBatch.executeNativeInvocation',
                    async () => await this.nativePluginExecutor.execute(item)
                )
            )
        )
    }
}
