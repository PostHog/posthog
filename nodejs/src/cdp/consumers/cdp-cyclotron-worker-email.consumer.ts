import { logger } from '~/common/utils/logger'
import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import {
    InFlightRegistry,
    callsSettledWithin,
    deferralDelayMs,
    fileBytesOf,
    inFlightLimitsFor,
} from '../services/messaging/in-flight-registry'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

// A send's result is written within this long of its deadline, so a stopping pod still writes it before the consumer's
// stop deadline. Calls still running after it keep the send's reservation, not its result.
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

    // A send with files leaves its batch once admitted, so its downloads never hold the next dequeue. The returned
    // background task covers it, so the job queue's stop waits for it as for any result write.
    public override async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        const plain: CyclotronJobInvocation[] = []
        const sends: Promise<void>[] = []
        const deferrals: { invocation: CyclotronJobInvocation; scheduledAt: Date }[] = []
        for (const invocation of invocations) {
            const fileBytes = fileBytesOf(invocation)
            if (fileBytes === null || invocation.cancelRequestedAt) {
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
        const deferring = deferrals.length ? this.deferWithHeartbeat(deferrals) : Promise.resolve()
        // Settled results never reject, so a send that fails while the plain batch runs leaves no unhandled rejection.
        const besideTheBatch = Promise.allSettled([deferring, ...sends])

        let batch: Awaited<ReturnType<CdpCyclotronWorkerHogFlow['processBatch']>>
        try {
            batch = await super.processBatch(plain)
        } catch (error) {
            await besideTheBatch
            throw error
        }
        return {
            backgroundTask: settleAll([batch.backgroundTask, besideTheBatch.then(rethrowFirstFailure)]),
            invocationResults: batch.invocationResults,
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
        const { backgroundTask } = await super.processBatch([withoutDeferralCount(invocation)])
        await backgroundTask
    }

    // Only a send with files has calls to wait for, so a plain batch writes at once.
    protected override async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        await callsSettledWithin(CALLS_SETTLE_BEFORE_WRITE_MS)
        await super.queueInvocationResults(results)
    }
}

function registryFor(config: PluginsServerConfig): InFlightRegistry {
    const admission = inFlightLimitsFor({
        memoryFraction: config.CDP_EMAIL_ATTACHMENTS_MEMORY_FRACTION,
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
    return {
        invocation: {
            ...invocation,
            queueMetadata: { ...invocation.queueMetadata, attachmentDeferrals: earlierDeferrals + 1 },
        },
        scheduledAt: new Date(Date.now() + deferralDelayMs(earlierDeferrals)),
    }
}

// The count only grows the delay between deferrals in a row, and marks a deferred dequeue for the lateness metric.
function withoutDeferralCount(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
    if (invocation.queueMetadata?.attachmentDeferrals === undefined) {
        return invocation
    }
    const { attachmentDeferrals: _, ...queueMetadata } = invocation.queueMetadata
    return { ...invocation, queueMetadata }
}

function rethrowFirstFailure(settled: PromiseSettledResult<unknown>[]): void {
    const failed = settled.find((outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected')
    if (failed) {
        throw failed.reason
    }
}

async function settleAll(work: Promise<unknown>[]): Promise<void> {
    rethrowFirstFailure(await Promise.allSettled(work))
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
