import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import { EMAIL_TRANSACTIONAL_QUEUE } from '../services/messaging/email-queues'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

export class CdpCyclotronWorkerEmailTransactional extends CdpCyclotronWorkerEmail {
    protected override name = 'CdpCyclotronWorkerEmailTransactional'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = EMAIL_TRANSACTIONAL_QUEUE
    }
}
