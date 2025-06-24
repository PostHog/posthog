import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

export class CdpCyclotronWorkerHogFlow extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerHogFlow'

    constructor(hub: Hub) {
        super(hub, 'hogflow')
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        const loadedInvocations = await this.loadHogFlows(invocations)
        return await Promise.all(loadedInvocations.map((item) => this.hogFlowExecutor.execute(item)))
    }

    protected async loadHogFlows(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationHogFlow[]> {
        const loadedInvocations: CyclotronJobInvocationHogFlow[] = []
        const failedInvocations: CyclotronJobInvocation[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId)
                if (!hogFlow) {
                    logger.error('⚠️', 'Error finding hog flow', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

                    return null
                }

                loadedInvocations.push({
                    ...item,
                    state: item.state as CyclotronJobInvocationHogFlow['state'],
                    hogFlow,
                })
            })
        )

        await this.cyclotronJobQueue.dequeueInvocations(failedInvocations)

        return loadedInvocations
    }
}
