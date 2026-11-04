import { DateTime } from 'luxon'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { logger } from '~/common/utils/logger'
import { UUIDT } from '~/common/utils/utils'
import { Team } from '~/types'

import { HogFlow } from '../../schema/hogflow'
import { HogFunctionInvocationGlobals } from '../../types'
import { convertToHogFunctionFilterGlobal } from '../../utils/hog-function-filtering'
import { JobQueue } from '../job-queue/job-queue.interface'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EMAIL_QUEUE_PRIORITY, EmailQueuePriorityClass, cdpEmailQueuedTotal } from '../messaging/email-priority'
import { EmailStatusService, uuidtCreatedAt } from '../messaging/email-status.service'
import { EmailSuppressionService } from '../messaging/email-suppression.service'
import { EmailValidationService } from '../messaging/email-validation.service'
import { HogInvocationResultsService } from '../monitoring/hog-invocation-results.service'
import { createHogFlowInvocation } from './hogflow-executor.service'
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
                        this.writeStatus(team.id, reservation.invocationId, 'scheduled')
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
        this.writeStatus(team.id, invocation.id, scheduledAt ? 'scheduled' : 'queued')
        // Best-effort rows, so the answer waits for the hand-off to Kafka (flushed on shutdown) but not the acks.
        const { produced } = await this.deps.invocationResultsRows.handOffQueuedRows()
        void produced.catch((error) => warnTelemetryFlushFailed(error, invocation.id))

        return { outcome: 'queued', invocationId: invocation.id, scheduledAt: scheduledAt?.toISOString() ?? null }
    }

    private writeStatus(teamId: number, messageId: string, status: 'queued' | 'scheduled'): void {
        this.deps.emailStatus.queue({ teamId, messageId, status })
        void this.deps.emailStatus.flush().catch((error) => warnTelemetryFlushFailed(error, messageId))
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
        // The lookups run at the same time, and the checks below await them in order, so the first refusal in that
        // order wins. The MX check's DNS lookup runs even when an earlier check refuses, which is acceptable because
        // refusals are rare and the verdict is cached per domain.
        const suspension = this.deps.teamWorkflowsConfig.getEmailSendingSuspension(teamId)
        const suppressed = this.deps.emailSuppression.isSuppressed(teamId, to, { transactional: true })
        const quota = checkHogFlowQuotaLimits(hogFlow, teamId, this.deps.quotaLimiting)
        // A DNS failure lets the send through.
        const recipientSkipReason = this.deps.emailValidation.getRecipientSkipReason(teamId, to)
        // An earlier refusal returns before the later lookups are awaited, so their failures must not go unhandled.
        const lookups: Promise<unknown>[] = [suspension, suppressed, quota, recipientSkipReason]
        for (const lookup of lookups) {
            lookup.catch(() => undefined)
        }

        if (await suspension) {
            return 'sending_suspended'
        }
        if (hogFlow.email_sending_paused_at) {
            return 'sending_paused'
        }
        if (await suppressed) {
            return 'recipient_suppressed'
        }
        if ((await quota).isLimited) {
            return 'quota_limited'
        }
        if (await recipientSkipReason) {
            return 'recipient_unreachable'
        }
        return null
    }
}
