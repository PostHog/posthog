import { DateTime } from 'luxon'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { UUID, UUIDT } from '~/common/utils/utils'
import { Team } from '~/types'

import { HogFlow } from '../../schema/hogflow'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, HogFunctionInvocationGlobals } from '../../types'
import { convertToHogFunctionFilterGlobal } from '../../utils/hog-function-filtering'
import { createCanceledInvocationResult } from '../../utils/invocation-utils'
import type { CyclotronV2JobProducer } from '../cyclotron-v2'
import { v2JobToInvocation } from '../cyclotron-v2/job-codec'
import type { CyclotronV2UnclaimedEmailCursor } from '../cyclotron-v2/types'
import type { InvocationResultsService } from '../invocation-results.service'
import { JobQueue } from '../job-queue/job-queue.interface'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EMAIL_QUEUE_PRIORITY, EmailQueuePriorityClass, cdpEmailQueuedTotal } from '../messaging/email-priority'
import { EmailStatusService, uuidtCreatedAt } from '../messaging/email-status.service'
import { EmailSuppressionService } from '../messaging/email-suppression.service'
import { EmailValidationService } from '../messaging/email-validation.service'
import { HogInvocationResultsService } from '../monitoring/hog-invocation-results.service'
import { createHogFlowInvocation } from './hogflow-executor.service'
import type { HogFlowManagerService } from './hogflow-manager.service'
import { checkHogFlowQuotaLimits } from './hogflow-quota-limiting'
import { TRANSACTIONAL_EMAIL_EVENT } from './hogflow-sensitivity'
import { IdempotencyKeys } from './idempotency-keys'
import {
    TransactionalEmailRequest,
    TransactionalEmailStageTimer,
    TransactionalSendRefusal,
} from './transactional-email'

const ACCEPTED_SEND_FINGERPRINT_MARKER = 'accepted_send'
const SCHEDULED_AT_FINGERPRINT_MARKER = 'scheduled_at'
// Counted from the message's creation, so a later reschedule cannot extend it.
const MAX_SCHEDULE_AHEAD_MS = 30 * 24 * 60 * 60 * 1000
const PRIORITY_CLASS: EmailQueuePriorityClass = 'fast'

// A request without `scheduled_at` keeps the fingerprint that older versions store, so their keys still match.
const transactionalEmailFingerprint = (
    hogFlowId: string,
    { to, distinct_id, variables, send }: TransactionalEmailRequest,
    scheduledAt: Date | null
): string => {
    const request: unknown[] = [hogFlowId, to, distinct_id, variables]
    if (send) {
        request.push(ACCEPTED_SEND_FINGERPRINT_MARKER, send)
    }
    if (scheduledAt) {
        request.push(SCHEDULED_AT_FINGERPRINT_MARKER, scheduledAt.toISOString())
    }
    return IdempotencyKeys.fingerprint(request)
}

const warnTelemetryFlushFailed = (error: unknown, invocationId: string): void => {
    logger.warn('⚠️', 'Transactional email telemetry flush failed', {
        error: error instanceof Error ? error.message : String(error),
        invocation_id: invocationId,
    })
}

const writeStatus = (
    emailStatus: EmailStatusService,
    teamId: number,
    messageId: string,
    status: 'queued' | 'scheduled' | 'canceled'
): void => {
    emailStatus.queue({ teamId, messageId, status })
    void emailStatus.flush().catch((error) => warnTelemetryFlushFailed(error, messageId))
}

export type TransactionalSendsDeps = {
    siteUrl: string
    idempotencyKeys: IdempotencyKeys
    queue: Pick<JobQueue, 'queueInvocations'>
    invocationResultsRows: HogInvocationResultsService
    emailStatus: EmailStatusService
    teamWorkflowsConfig: TeamWorkflowsConfigService
    emailSuppression: EmailSuppressionService
    emailValidation: EmailValidationService
    quotaLimiting: QuotaLimiting
}

export type TransactionalSendResult =
    | { outcome: 'queued' | 'replayed'; invocationId: string; scheduledAt: string | null }
    | { outcome: TransactionalSendRefusal }

export class TransactionalSends {
    constructor(private readonly deps: TransactionalSendsDeps) {}

    async accept(
        team: Team,
        hogFlow: HogFlow,
        request: TransactionalEmailRequest,
        stages: TransactionalEmailStageTimer
    ): Promise<TransactionalSendResult> {
        const { idempotencyKeys } = this.deps
        const { to, idempotency_key: idempotencyKey } = request
        const requestedAt = request.scheduled_at ? new Date(request.scheduled_at) : null

        stages.start('build')
        const invocation = this.buildInvocation(team, hogFlow, request)
        const fingerprint = transactionalEmailFingerprint(hogFlow.id, request, requestedAt)
        if (idempotencyKey) {
            // Checked before the quota, so a retry of a send that went out gets its answer even
            // when the team has hit its quota since.
            stages.start('idempotency')
            const reservation = await idempotencyKeys.reserve(team.id, idempotencyKey, fingerprint, invocation.id)
            switch (reservation.status) {
                case 'replayed': {
                    const scheduledAt = reservation.scheduledAt ?? null
                    if (scheduledAt) {
                        writeStatus(this.deps.emailStatus, team.id, reservation.invocationId, 'scheduled')
                    }
                    return { outcome: 'replayed', invocationId: reservation.invocationId, scheduledAt }
                }
                case 'in_flight':
                    return { outcome: 'idempotency_key_in_flight' }
                case 'conflict':
                    return { outcome: 'idempotency_key_reused' }
                case 'unavailable':
                    return { outcome: 'idempotency_unavailable' }
            }
        }
        const tooFarAhead =
            requestedAt !== null &&
            requestedAt.getTime() > uuidtCreatedAt(invocation.id).getTime() + MAX_SCHEDULE_AHEAD_MS
        const scheduledAt = !tooFarAhead && requestedAt && requestedAt.getTime() > Date.now() ? requestedAt : null
        if (scheduledAt) {
            invocation.queueScheduledAt = DateTime.fromJSDate(scheduledAt)
            invocation.state.scheduledAt = scheduledAt.toISOString()
        }
        try {
            stages.start('checks')
            const refusal = tooFarAhead ? 'invalid_scheduled_at' : await this.refusal(team.id, hogFlow, to)
            if (refusal) {
                if (idempotencyKey) {
                    stages.start('idempotency')
                    await idempotencyKeys.release(team.id, idempotencyKey, invocation.id)
                }
                return { outcome: refusal }
            }
            stages.start('queue_insert')
            this.deps.invocationResultsRows.queueLifecycleRow(invocation, 'running')
            try {
                await this.deps.queue.queueInvocations([invocation])
            } catch (error) {
                this.deps.invocationResultsRows.dropQueuedRowsFor([invocation.id])
                throw error
            }
            cdpEmailQueuedTotal.labels(PRIORITY_CLASS).inc()
        } catch (error) {
            // Nothing was queued, so the caller's retry with the same key must be able to send.
            if (idempotencyKey) {
                stages.start('idempotency')
                await idempotencyKeys.release(team.id, idempotencyKey, invocation.id)
            }
            throw error
        }
        if (idempotencyKey) {
            stages.start('idempotency')
            await idempotencyKeys.markQueued(
                team.id,
                idempotencyKey,
                fingerprint,
                invocation.id,
                scheduledAt?.toISOString()
            )
        }
        stages.start('metrics_flush')
        writeStatus(this.deps.emailStatus, team.id, invocation.id, scheduledAt ? 'scheduled' : 'queued')
        // Best-effort rows, so the answer waits for the hand-off to Kafka (flushed on shutdown) but not the acks.
        const { produced } = await this.deps.invocationResultsRows.handOffQueuedRows()
        void produced.catch((error) => warnTelemetryFlushFailed(error, invocation.id))

        return { outcome: 'queued', invocationId: invocation.id, scheduledAt: scheduledAt?.toISOString() ?? null }
    }

    private buildInvocation(team: Team, hogFlow: HogFlow, request: TransactionalEmailRequest) {
        const { to, distinct_id: distinctId, variables, send } = request
        const event: HogFunctionInvocationGlobals['event'] = {
            uuid: new UUIDT().toString(),
            event: TRANSACTIONAL_EMAIL_EVENT,
            distinct_id: distinctId,
            timestamp: DateTime.now().toISO(),
            url: '',
            // The email step's recipient reads this.
            properties: { to },
            elements_chain: '',
        }
        const triggerGlobals: HogFunctionInvocationGlobals = {
            event,
            project: {
                id: team.id,
                name: team.name,
                url: `${this.deps.siteUrl}/project/${team.id}`,
            },
            variables,
        }
        const filterGlobals = convertToHogFunctionFilterGlobal({
            event,
            person: undefined,
            groups: {},
            variables,
        })

        const invocation = createHogFlowInvocation(triggerGlobals, hogFlow, filterGlobals)
        if (send) {
            invocation.state.send = send
        }
        // The run skips the trigger pipeline that counts runs for event-triggered workflows, so the email
        // worker counts it instead.
        invocation.state.triggerMetricPending = true
        // Straight to the email queue: the flow's only step is the email, so a hop through the
        // workflow queue would only add latency to a password reset or a verification code.
        invocation.queue = 'email'
        invocation.queuePriority = EMAIL_QUEUE_PRIORITY[PRIORITY_CLASS]
        return invocation
    }

    // The email worker skips a send for these reasons too, but only after the caller has its answer. Checking them
    // here tells the caller that the email will not go out. The worker keeps its checks, because the state can
    // change while the job waits on the queue.
    private async refusal(teamId: number, hogFlow: HogFlow, to: string): Promise<TransactionalSendRefusal | null> {
        if (hogFlow.status !== 'active') {
            return 'not_sendable'
        }
        if (await this.deps.teamWorkflowsConfig.getEmailSendingSuspension(teamId)) {
            return 'sending_suspended'
        }
        if (hogFlow.email_sending_paused_at) {
            return 'sending_paused'
        }
        if (await this.deps.emailSuppression.isSuppressed(teamId, to, { transactional: true })) {
            return 'recipient_suppressed'
        }
        const { isLimited } = await checkHogFlowQuotaLimits(hogFlow, teamId, this.deps.quotaLimiting)
        if (isLimited) {
            return 'quota_limited'
        }
        // Last, because a cache miss costs a DNS lookup. A DNS failure lets the send through.
        if (await this.deps.emailValidation.getRecipientSkipReason(teamId, to)) {
            return 'recipient_unreachable'
        }
        return null
    }
}

export type ScheduledTransactionalSendsDeps = {
    jobs: Pick<CyclotronV2JobProducer, 'cancelUnclaimed' | 'rescheduleUnclaimed' | 'listUnclaimed'>
    hogFlows: Pick<HogFlowManagerService, 'getHogFlowCheckingPrimaryOnMiss'>
    invocationResults: Pick<InvocationResultsService, 'monitoringService' | 'invocationResultsRowsService'>
    emailStatus: EmailStatusService
}

export type ScheduledSendCancelResult = { outcome: 'canceled' } | { outcome: 'claimed' | 'not_found' }

export type ScheduledSendRescheduleResult =
    | { outcome: 'rescheduled'; scheduledAt: string }
    | { outcome: 'invalid_scheduled_at' | 'canceled' | 'claimed' | 'not_found' }

export type ScheduledSend = { id: string; to: string | null; scheduled_at: string; created_at: string }

export type ScheduledSendListResult =
    | { outcome: 'listed'; results: ScheduledSend[]; next: string | null }
    | { outcome: 'invalid_cursor' }

// The cursor names the last send of a page, as base64url JSON of [scheduled time, message id].
const encodeCursor = ({ scheduled, id }: CyclotronV2UnclaimedEmailCursor): string =>
    Buffer.from(JSON.stringify([scheduled.toISOString(), id])).toString('base64url')

const decodeCursor = (cursor: string): CyclotronV2UnclaimedEmailCursor | null => {
    let decoded: unknown
    try {
        decoded = parseJSON(Buffer.from(cursor, 'base64url').toString('utf-8'))
    } catch {
        return null
    }
    if (!Array.isArray(decoded) || decoded.length !== 2) {
        return null
    }
    const [time, id] = decoded
    const scheduled = typeof time === 'string' ? new Date(time) : null
    if (!scheduled || isNaN(scheduled.getTime()) || typeof id !== 'string' || !UUID.validateString(id, false)) {
        return null
    }
    return { scheduled, id }
}

export class ScheduledTransactionalSends {
    constructor(private readonly deps: ScheduledTransactionalSendsDeps) {}

    async list(teamId: number, cursor: string | undefined, limit: number): Promise<ScheduledSendListResult> {
        const after = cursor === undefined ? null : decodeCursor(cursor)
        if (cursor !== undefined && !after) {
            return { outcome: 'invalid_cursor' }
        }
        // One row past the page tells whether a next page exists.
        const jobs = await this.deps.jobs.listUnclaimed(teamId, after, limit + 1)
        const page = jobs.slice(0, limit)
        const last = page[page.length - 1]
        return {
            outcome: 'listed',
            results: page.map((job) => ({
                id: job.id,
                to: job.to,
                scheduled_at: job.scheduled.toISOString(),
                created_at: job.created.toISOString(),
            })),
            next: jobs.length > limit ? encodeCursor(last) : null,
        }
    }

    async cancel(teamId: number, messageId: string): Promise<ScheduledSendCancelResult> {
        if (!UUID.validateString(messageId, false)) {
            return { outcome: 'not_found' }
        }
        const result = await this.deps.jobs.cancelUnclaimed(teamId, messageId)
        switch (result.outcome) {
            case 'canceled':
                await this.recordCanceledRun(v2JobToInvocation(result.job))
                return { outcome: 'canceled' }
            case 'already_canceled':
                return { outcome: 'canceled' }
            default:
                return { outcome: result.outcome }
        }
    }

    async reschedule(teamId: number, messageId: string, requestedAt: Date): Promise<ScheduledSendRescheduleResult> {
        if (!UUID.validateString(messageId, false)) {
            return { outcome: 'not_found' }
        }
        const now = new Date()
        // A time that has passed sends now, even past the bound, as the send route does.
        if (requestedAt > now && requestedAt.getTime() > uuidtCreatedAt(messageId).getTime() + MAX_SCHEDULE_AHEAD_MS) {
            return { outcome: 'invalid_scheduled_at' }
        }
        const scheduledAt = requestedAt > now ? requestedAt : now
        const result = await this.deps.jobs.rescheduleUnclaimed(teamId, messageId, scheduledAt)
        if (result.outcome !== 'rescheduled') {
            return { outcome: result.outcome }
        }
        writeStatus(this.deps.emailStatus, teamId, messageId, 'scheduled')
        return { outcome: 'rescheduled', scheduledAt: scheduledAt.toISOString() }
    }

    // No worker ever sees a job canceled before its claim, so this writes what the worker writes for a canceled run.
    private async recordCanceledRun(job: CyclotronJobInvocation): Promise<void> {
        const { monitoringService, invocationResultsRowsService } = this.deps.invocationResults
        // The loaded flow gives the metrics their version. A flow that is gone still cancels.
        const hogFlow = await this.deps.hogFlows.getHogFlowCheckingPrimaryOnMiss(job.functionId).catch(() => null)
        const result = createCanceledInvocationResult(job, 'Run canceled before it was sent', hogFlow ?? undefined)
        if ((job.state as CyclotronJobInvocationHogFlow['state'] | null)?.triggerMetricPending) {
            result.metrics.push({
                team_id: job.teamId,
                app_source_id: job.functionId,
                metric_kind: 'other',
                metric_name: 'triggered',
                count: 1,
            })
        }
        monitoringService.queueInvocationResults([result])
        invocationResultsRowsService.queueInvocationResults([result])
        writeStatus(this.deps.emailStatus, job.teamId, job.id, 'canceled')
        void monitoringService.flush().catch((error) => warnTelemetryFlushFailed(error, job.id))
        const { produced } = await invocationResultsRowsService.handOffQueuedRows()
        void produced.catch((error) => warnTelemetryFlushFailed(error, job.id))
    }
}
