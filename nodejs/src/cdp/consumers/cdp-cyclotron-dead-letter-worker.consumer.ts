import { PluginsServerConfig } from '../../types'
import { ConsumerOptions, JobQueue } from '../services/job-queue/job-queue.interface'
import { CrashGuard } from '../services/poison-batch/crash-guard'
import { InvocationQuarantine } from '../services/poison-batch/quarantine-invocations'
import { DEAD_LETTER_QUEUE } from '../types'
import { CdpCyclotronWorker, CdpCyclotronWorkerDeps } from './cdp-cyclotron-worker.consumer'

/**
 * Runs the invocations the hog worker diverted to the dead letter topic because their batch kept crashing it.
 * The diverted batch can hold healthy invocations next to the one at fault. This worker runs them one at a
 * time, so its crash guard flags only the invocation at fault, and quarantines it instead of running it again.
 */
export class CdpCyclotronDeadLetterWorker extends CdpCyclotronWorker {
    private quarantine: InvocationQuarantine

    constructor(config: PluginsServerConfig, deps: CdpCyclotronWorkerDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue, DEAD_LETTER_QUEUE)
        this.quarantine = new InvocationQuarantine(
            this.name,
            this.invocationResultsService.invocationResultsRowsService
        )
    }

    protected override consumerOptions(): ConsumerOptions {
        const settings = this.crashGuardSettings
        return {
            // A batch that crashed the dead letter worker is quarantined whole, so it must hold only the message at
            // fault. A second message fetched while the first one's background task runs would be counted with it.
            fetchBatchSize: 1,
            maxBackgroundTasks: 1,
            crashGuard: settings
                ? ({ groupId }) =>
                      new CrashGuard(
                          // The dead letter worker has no later stage to hand a message to, so in shadow mode it would
                          // crash on the message forever and hold back every message behind it.
                          { ...settings, mode: 'enforce' },
                          groupId,
                          (messages) => this.quarantine.setAside(messages)
                      )
                : undefined,
        }
    }
}
