import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { PluginsServerConfig } from '../../types'
import { ConsumerOptions, JobQueue } from '../services/job-queue/job-queue.interface'
import { HogWatcherFunctionState, HogWatcherState, sameWatcherStates } from '../services/monitoring/hog-watcher.service'
import { CrashGuard } from '../services/poison-batch/crash-guard'
import { createQuarantineAutoDisable } from '../services/poison-batch/quarantine-auto-disable'
import { InvocationQuarantine, recordTerminal } from '../services/poison-batch/quarantine-invocations'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, DEAD_LETTER_QUEUE } from '../types'
import { dualRead } from '../utils/dual-store'
import { CdpCyclotronWorker, CdpCyclotronWorkerDeps } from './cdp-cyclotron-worker.consumer'

const disabledFunctionInvocationsSkipped = new Counter({
    name: 'cdp_dlq_disabled_function_invocations_skipped_total',
    help: 'Invocations the dead letter worker skipped because the watcher disabled their function. recorded wrote a terminal failure row. unrecorded skipped the invocation without a row, because invocation results are off or the invocation names no team or id. failed could not write the row, so the batch fails and is retried.',
    labelNames: ['outcome'],
})

export const SKIPPED_FUNCTION_DISABLED_ERROR_KIND = 'skipped_function_disabled'

const SKIPPED_FUNCTION_DISABLED_FAILURE = {
    errorKind: SKIPPED_FUNCTION_DISABLED_ERROR_KIND,
    error: "This invocation was skipped because the function's status is Disabled.",
}

/**
 * Runs the invocations the hog worker diverted to the dead letter topic because their batch kept crashing it.
 * The diverted batch can hold healthy invocations next to the one at fault. This worker runs them one at a
 * time, so its crash guard flags only the invocation at fault, and quarantines it instead of running it again.
 */
export class CdpCyclotronDeadLetterWorker extends CdpCyclotronWorker {
    private quarantine: InvocationQuarantine

    constructor(config: PluginsServerConfig, deps: CdpCyclotronWorkerDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue, DEAD_LETTER_QUEUE)
        const autoDisable = this.crashGuardSettings
            ? createQuarantineAutoDisable(config, {
                  valkey: this.crashGuardSettings.valkey,
                  getHogFunction: (id) => this.hogFunctionManager.getHogFunction(id),
                  hogWatcher: this.hogWatcher,
                  hogWatcherMirror: this.hogWatcherMirror,
              })
            : null
        this.quarantine = new InvocationQuarantine(
            this.name,
            this.invocationResultsService.invocationResultsRowsService,
            autoDisable
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

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        return await super.processInvocations(await this.skipDisabledFunctions(invocations))
    }

    /**
     * The events consumer stops queuing a function once the watcher disables it, but invocations already on the
     * dead letter topic still arrive here. Each of them can crash the worker until it is quarantined, so the
     * worker skips them instead. The read is fresh rather than cached, so an invocation right behind the quarantine
     * that disabled its function is skipped too.
     */
    private async skipDisabledFunctions(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocation[]> {
        const functionIds = [...new Set(invocations.map((x) => x.functionId).filter(Boolean))]
        if (!functionIds.length) {
            return invocations
        }

        let states: Record<string, HogWatcherFunctionState>
        try {
            states = await dualRead(
                'hog-watcher.getEffectiveStates',
                () => this.hogWatcher.getEffectiveStates(functionIds),
                () => this.hogWatcherMirror.getEffectiveStates(functionIds),
                sameWatcherStates
            )
        } catch (error) {
            logger.warn('⚠️', `${this.name} - could not read the function states, so the batch runs unchecked`, {
                functionIds,
                error: String(error),
            })
            return invocations
        }

        const skipped = invocations.filter((x) => states[x.functionId]?.state === HogWatcherState.disabled)
        if (!skipped.length) {
            return invocations
        }

        const rows = this.invocationResultsService.invocationResultsRowsService
        const outcomes = await Promise.all(
            skipped.map((invocation) => recordTerminal(rows, invocation, SKIPPED_FUNCTION_DISABLED_FAILURE))
        )
        skipped.forEach((invocation, i) => {
            disabledFunctionInvocationsSkipped.labels(outcomes[i]).inc()
            if (outcomes[i] === 'failed') {
                return
            }
            logger.warn('⏭️', `${this.name} - skipped an invocation of a disabled function`, {
                functionId: invocation.functionId,
                teamId: invocation.teamId,
                invocationId: invocation.id,
                errorKind: SKIPPED_FUNCTION_DISABLED_ERROR_KIND,
                recorded: outcomes[i] === 'recorded',
            })
        })
        if (outcomes.includes('failed')) {
            throw new Error('Could not record the terminal failure of an invocation of a disabled function')
        }

        return invocations.filter((x) => !skipped.includes(x))
    }
}
