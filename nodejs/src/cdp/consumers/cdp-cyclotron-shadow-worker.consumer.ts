import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpCyclotronWorker, CdpCyclotronWorkerHub } from './cdp-cyclotron-worker.consumer'

/**
 * Shadow worker that consumes from the shadow Cyclotron database.
 * Loads hog functions and produces mock successful results without making real HTTP calls.
 * This exercises the full queue infrastructure (dual-write, dequeue, result handling)
 * without side effects.
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
        const loadedInvocations = await this.loadHogFunctions(invocations)

        return loadedInvocations.map((invocation) => createInvocationResult(invocation, {}, { finished: true }))
    }
}
