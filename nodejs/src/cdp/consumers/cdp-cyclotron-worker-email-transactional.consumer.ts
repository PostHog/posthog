import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

export class CdpCyclotronWorkerEmailTransactional extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmailTransactional'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'emailtransactional'
    }
}
