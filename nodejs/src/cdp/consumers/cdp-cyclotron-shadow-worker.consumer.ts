import { shadowFetchContext } from '../services/hog-executor.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorker, CdpCyclotronWorkerHub } from './cdp-cyclotron-worker.consumer'

/**
 * Shadow worker that consumes from the shadow Cyclotron database.
 * Executes the full invocation pipeline (including bytecode) but with no-op HTTP fetches,
 * scoped via AsyncLocalStorage so other workers in the same process are unaffected.
 */
export class CdpCyclotronShadowWorker extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronShadowWorker'

    constructor(hub: CdpCyclotronWorkerHub) {
        const shadowHub: CdpCyclotronWorkerHub = {
            ...hub,
            CYCLOTRON_DATABASE_URL: hub.CYCLOTRON_SHADOW_DATABASE_URL,
            CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'postgres',
            CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING: '*:postgres',
            CDP_CYCLOTRON_SHADOW_WRITE_ENABLED: false,
        }
        super(shadowHub)
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        return shadowFetchContext.run(true, () => super.processInvocations(invocations))
    }
}
