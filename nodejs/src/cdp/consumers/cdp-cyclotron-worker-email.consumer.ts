import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'email'
    }

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const results = await super.processInvocations(invocations)
        results.forEach(countPendingTrigger)
        return results
    }
}

// The transactional email API queues its runs straight onto this queue, so this worker counts them as triggered.
// The flag is cleared on the state that the job queue persists, so a throttled or rate-limited reschedule of the
// same job does not count it again. A canceled run counts too, because the API accepted it.
function countPendingTrigger(result: CyclotronJobInvocationResult): void {
    const state = result.invocation.state as CyclotronJobInvocationHogFlow['state'] | null | undefined
    if (!state?.triggerMetricPending) {
        return
    }
    delete state.triggerMetricPending
    result.metrics.push({
        team_id: result.invocation.teamId,
        app_source_id: result.invocation.functionId,
        metric_kind: 'other',
        metric_name: 'triggered',
        count: 1,
    })
}
