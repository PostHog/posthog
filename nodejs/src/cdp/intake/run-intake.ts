import { JobQueue } from '~/cdp/services/job-queue/job-queue.interface'
import { HogInvocationResultsService } from '~/cdp/services/monitoring/hog-invocation-results.service'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'

export type Run = {
    invocation: CyclotronJobInvocationHogFlow
}

export type Committed = { runId: string; outcome: 'created' }

export type RunIntakeDeps = {
    hogflowQueue: Pick<JobQueue, 'queueInvocations'>
    invocationResultsRowsService: HogInvocationResultsService
}

export class RunIntake {
    constructor(private deps: RunIntakeDeps) {}

    // Dropped on an insert error, so a run that never reached the queue leaves no 'running' row behind.
    async launch(runs: Run[], _options: { wait: 'committed' }): Promise<Committed[]> {
        const invocations = runs.map((run) => run.invocation)
        // Queued before queueInvocations serializes the invocations, because queueLifecycleRow stamps
        // `state.firstScheduledAt` and only a stamp set before serialization reaches cyclotron.
        for (const invocation of invocations) {
            this.deps.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }
        try {
            await this.deps.hogflowQueue.queueInvocations(invocations)
        } catch (error) {
            this.deps.invocationResultsRowsService.dropQueuedRowsFor(invocations.map((invocation) => invocation.id))
            throw error
        }
        return invocations.map((invocation) => ({ runId: invocation.id, outcome: 'created' }))
    }
}
