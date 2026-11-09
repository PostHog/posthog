import { logger } from '~/common/utils/logger'
import { PluginsServerConfig } from '~/types'

import { reportResultWriteFailure } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import {
    InFlightRegistry,
    callsSettledWithin,
    deferralDelayMs,
    exceedsLargestSend,
    fileBytesOf,
    inFlightLimitsFor,
} from '../services/messaging/in-flight-registry'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { settleAllThenThrowFirst } from '../utils/settle-all'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

const CALLS_SETTLE_BEFORE_WRITE_MS = 3_000

export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'
    private readonly sendsWithFiles: InFlightRegistry

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        jobQueue: JobQueue,
        sendsWithFiles: InFlightRegistry = registryFor(config)
    ) {
        super(config, deps, jobQueue)
        this.queue = 'email'
        this.sendsWithFiles = sendsWithFiles
    }

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const results = await super.processInvocations(invocations)
        results.forEach(countPendingTrigger)
        return results
    }

    public override async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        const plain: CyclotronJobInvocation[] = []
        const sends: Promise<void>[] = []
        const deferrals: { invocation: CyclotronJobInvocation; scheduledAt: Date }[] = []
        for (const invocation of invocations) {
            const fileBytes = fileBytesOf(invocation)
            if (fileBytes === null || exceedsLargestSend(fileBytes) || invocation.cancelRequestedAt) {
                plain.push(invocation)
                continue
            }
            const admission = this.sendsWithFiles.tryStart(fileBytes, () => this.runSendWithFiles(invocation))
            if ('started' in admission) {
                sends.push(admission.started)
            } else {
                deferrals.push(deferral(invocation))
            }
        }
        const besideTheBatch = [deferrals.length ? this.deferWithHeartbeat(deferrals) : Promise.resolve(), ...sends]
        const besideTheBatchSettled = Promise.allSettled(besideTheBatch)

        let batch: Awaited<ReturnType<CdpCyclotronWorkerHogFlow['processBatch']>>
        try {
            batch = await super.processBatch(plain)
        } catch (error) {
            this.reportFailures(await besideTheBatchSettled)
            throw error
        }
        return {
            backgroundTask: settleAllThenThrowFirst([batch.backgroundTask, ...besideTheBatch]),
            invocationResults: batch.invocationResults,
        }
    }

    private reportFailures(settled: PromiseSettledResult<unknown>[]): void {
        for (const outcome of settled) {
            if (outcome.status === 'rejected') {
                reportResultWriteFailure(this.queue, outcome.reason)
            }
        }
    }

    private async deferWithHeartbeat(
        deferrals: { invocation: CyclotronJobInvocation; scheduledAt: Date }[]
    ): Promise<void> {
        const stopHeartbeat = this.startPeriodicHeartbeat(deferrals.map(({ invocation }) => invocation))
        try {
            await this.cyclotronJobQueue.deferInvocations(deferrals)
        } finally {
            stopHeartbeat()
        }
    }

    private async runSendWithFiles(invocation: CyclotronJobInvocation): Promise<void> {
        const { backgroundTask } = await super.processBatch([withoutDeferralState(invocation)])
        await backgroundTask
    }

    protected override async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        await callsSettledWithin(CALLS_SETTLE_BEFORE_WRITE_MS)
        await super.queueInvocationResults(results)
    }
}

function registryFor(config: PluginsServerConfig): InFlightRegistry {
    const admission = inFlightLimitsFor({
        memoryFraction: config.CDP_EMAIL_ATTACHMENTS_MEMORY_BUDGET_FRACTION,
        maxInFlight: config.CDP_EMAIL_ATTACHMENTS_MAX_IN_FLIGHT,
        heartbeatIntervalMs: config.CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS,
    })
    if ('refusal' in admission) {
        logger.error('📧', 'The email worker refuses sends with files and defers each one', {
            reason: admission.refusal,
        })
        return new InFlightRegistry(null)
    }
    logger.info('📧', 'The email worker admits sends with files', admission.limits)
    return new InFlightRegistry(admission.limits)
}

function deferral(invocation: CyclotronJobInvocation): { invocation: CyclotronJobInvocation; scheduledAt: Date } {
    const earlierDeferrals: number = invocation.queueMetadata?.attachmentDeferrals ?? 0
    const now = Date.now()
    return {
        invocation: {
            ...invocation,
            queueMetadata: {
                ...invocation.queueMetadata,
                attachmentDeferrals: earlierDeferrals + 1,
                attachmentDueAt:
                    invocation.queueMetadata?.attachmentDueAt ?? invocation.queueScheduledAt?.toMillis() ?? now,
            },
        },
        scheduledAt: new Date(now + deferralDelayMs(earlierDeferrals)),
    }
}

function withoutDeferralState(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
    if (invocation.queueMetadata?.attachmentDeferrals === undefined) {
        return invocation
    }
    const { attachmentDeferrals: _, attachmentDueAt: __, ...queueMetadata } = invocation.queueMetadata
    return { ...invocation, queueMetadata }
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
