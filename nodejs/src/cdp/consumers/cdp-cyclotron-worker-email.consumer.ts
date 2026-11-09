import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { logger } from '~/common/utils/logger'
import { PluginsServerConfig } from '~/types'

import { CONSUMER_STOP_DEADLINE_MS, reportResultWriteFailure } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { LONGEST_WAIT_FOR_ROOM_MS } from '../services/messaging/attachment-horizon'
import { DAY_MS } from '../services/messaging/attachment-store'
import { ATTACHMENT_SEND_DEADLINE_MS } from '../services/messaging/email.service'
import {
    InFlightRegistry,
    callsSettledWithin,
    deferralDelayMs,
    exceedsLargestSend,
    fileBytesOf,
    firstDueAt,
    inFlightLimitsFor,
} from '../services/messaging/in-flight-registry'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { settleAllThenThrowFirst } from '../utils/settle-all'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

export const RESULT_WRITE_MARGIN_MS = 5_000
const ATTACHMENT_WAIT_EXPIRED = 'attachment_wait_expired'
const WAITED_TOO_LONG_MESSAGE = `${ATTACHMENT_WAIT_EXPIRED}: this email waited ${LONGEST_WAIT_FOR_ROOM_MS / DAY_MS} days for an email worker with room for its files, so it was not sent before its files could expire. Send it again.`
const waitedTooLongForRoom = new WeakSet<CyclotronJobInvocation>()
const CALLS_SETTLE_BEFORE_WRITE_MS = CONSUMER_STOP_DEADLINE_MS - ATTACHMENT_SEND_DEADLINE_MS - RESULT_WRITE_MARGIN_MS

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
        const expired = invocations.filter((invocation) => waitedTooLongForRoom.has(invocation))
        const results = [
            ...(await super.processInvocations(
                invocations.filter((invocation) => !waitedTooLongForRoom.has(invocation))
            )),
            ...expired.map((invocation) => this.failForWaitingTooLong(invocation)),
        ]
        results.forEach(countPendingTrigger)
        return results
    }

    private failForWaitingTooLong(invocation: CyclotronJobInvocation): CyclotronJobInvocationResult {
        const withFlowId = { ...invocation, hogFlow: { id: invocation.functionId } as HogFlow }
        const result = createInvocationResult(withFlowId, {}, { finished: true })
        result.error = WAITED_TOO_LONG_MESSAGE
        result.logs.push({ level: 'error', timestamp: DateTime.now(), message: WAITED_TOO_LONG_MESSAGE })
        this.invocationResultsService.emailStatusService.queueFailedJob(invocation, ATTACHMENT_WAIT_EXPIRED)
        return result
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
            } else if (Date.now() - firstDueAt(invocation, Date.now()) >= LONGEST_WAIT_FOR_ROOM_MS) {
                waitedTooLongForRoom.add(invocation)
                plain.push(invocation)
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
        attachmentStoreBucket: config.CDP_EMAIL_ATTACHMENTS_S3_BUCKET,
    })
    if ('refusal' in admission) {
        logger.error(
            '📧',
            `The email worker refuses sends with files. It defers each one, and fails it with ${ATTACHMENT_WAIT_EXPIRED} once it has waited ${LONGEST_WAIT_FOR_ROOM_MS / DAY_MS} days`,
            { reason: admission.refusal }
        )
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
                attachmentDueAt: firstDueAt(invocation, now),
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
