import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { logger } from '~/common/utils/logger'
import { UUID, UUIDT } from '~/common/utils/utils'
import { Team } from '~/types'

import { PublishSettlement } from '../../intake/intake-producer'
import { Claim, Committed, Produced, Recalled, Run, RunIntake, keyedRunId } from '../../intake/run-intake'
import { HogFlow } from '../../schema/hogflow'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    HogFunctionInvocationGlobals,
    IntegrationType,
} from '../../types'
import { EncryptedFields } from '../../utils/encryption-utils'
import { convertToHogFunctionFilterGlobal } from '../../utils/hog-function-filtering'
import { createCanceledInvocationResult } from '../../utils/invocation-utils'
import type { CyclotronV2JobProducer } from '../cyclotron-v2'
import { StateOpener, v2JobToInvocation } from '../cyclotron-v2/job-codec'
import { isLockTimeout } from '../cyclotron-v2/manager'
import type { InvocationResultsService } from '../invocation-results.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { AttachmentUploads, MessageBodySizing, SendRefusal } from '../messaging/attachment-uploads'
import { EMAIL_QUEUE_PRIORITY, EmailQueuePriorityClass, cdpEmailQueuedTotal } from '../messaging/email-priority'
import {
    EmailSkipReason,
    EmailStatusService,
    EmailStatusUpdate,
    isKeyedMessageId,
    jobTriggerEvent,
    messageCreatedAtOf,
    uuidtCreatedAt,
} from '../messaging/email-status.service'
import { EmailSuppressionService } from '../messaging/email-suppression.service'
import { EmailValidationService } from '../messaging/email-validation.service'
import { CodeSendSender, SandboxCodeSendRefusal, senderOfCodeSend } from '../messaging/sandbox/sandbox-code-send'
import { HogInvocationResultsService } from '../monitoring/hog-invocation-results.service'
import { EmailStep, FilesWorkflowShape } from './files-workflow-shape'
import { createHogFlowInvocation } from './hogflow-executor.service'
import type { HogFlowManagerService } from './hogflow-manager.service'
import { checkHogFlowQuotaLimits } from './hogflow-quota-limiting'
import { TRANSACTIONAL_EMAIL_EVENT } from './hogflow-sensitivity'
import { QueuedReply, SenderKind, requestFingerprint } from './idempotency-keys'
import {
    AcceptedSend,
    TransactionalEmailRequest,
    TransactionalEmailStageTimer,
    TransactionalSendRefusal,
    transactionalEmailRecipients,
} from './transactional-email'

const ACCEPTED_SEND_FINGERPRINT_MARKER = 'accepted_send'
const SCHEDULED_AT_FINGERPRINT_MARKER = 'scheduled_at'
const MAX_SCHEDULE_AHEAD_MS = 30 * 24 * 60 * 60 * 1000
const NO_ATTACHMENTS = { attachment_count: 0, attachment_bytes: 0 }
const PRIORITY_CLASS: EmailQueuePriorityClass = 'fast'
const RUN_SCOPE = 'transactional-email'
export const FINGERPRINT_PURPOSE = 'transactional_email_idempotency_fingerprint'
const ASYNC_REFUSAL_BUDGET_MS = 1_000

const refusalFailOpenCounter = new Counter({
    name: 'cdp_transactional_email_refusal_fail_open_total',
    help: 'Async-mode sends accepted without their refusal checks, because the lookups failed or ran past their budget, by reason.',
    labelNames: ['reason'] as const,
})

// A keyed id holds no time, so a keyed send is dated by its trigger event, which every reschedule carries along.
const createdAtOf = (messageId: string, event?: { timestamp?: unknown } | null): Date =>
    isKeyedMessageId(messageId) ? (messageCreatedAtOf(event) ?? new Date()) : uuidtCreatedAt(messageId)

const latestDueAtOf = (messageId: string, event?: { timestamp?: unknown } | null): Date =>
    new Date(createdAtOf(messageId, event).getTime() + MAX_SCHEDULE_AHEAD_MS)

const claimFor = (
    teamId: number,
    idempotencyKey: string | undefined,
    fingerprint: TransactionalEmailFingerprint
): Claim | undefined =>
    idempotencyKey
        ? { runId: keyedRunId(teamId, RUN_SCOPE, idempotencyKey), fingerprint: fingerprint.current }
        : undefined

type TransactionalEmailFingerprint = { current: string; alsoMatches: string[] }

const claimedBySameRequest = (fingerprint: TransactionalEmailFingerprint, claimed: string | undefined): boolean =>
    claimed !== undefined && fingerprint.alsoMatches.includes(claimed)

// Keyed, because the variables can hold a short login code that anyone who reads a store could guess offline from an
// unkeyed hash. A record signed under any configured key still matches after a rotation. So does the unkeyed hash of a
// record stored before keying, until the last such record expires.
const fingerprintsOf = (encryptedFields: EncryptedFields, request: unknown[]): string[] => {
    const unkeyed = requestFingerprint(request)
    return [...encryptedFields.signatures(FINGERPRINT_PURPOSE, unkeyed), unkeyed]
}

const transactionalEmailFingerprint = (
    encryptedFields: EncryptedFields,
    hogFlowId: string,
    { to, distinct_id, variables }: TransactionalEmailRequest,
    send: AcceptedSend | undefined,
    scheduledAt: Date | null
): TransactionalEmailFingerprint => {
    const request: unknown[] = [hogFlowId, to, distinct_id, variables]
    const schedule: unknown[] = scheduledAt ? [SCHEDULED_AT_FINGERPRINT_MARKER, scheduledAt.toISOString()] : []
    const shape: unknown[] = send
        ? [
              ...request,
              ACCEPTED_SEND_FINGERPRINT_MARKER,
              { ...send, from: senderTheCallerChose(send.from) },
              ...schedule,
          ]
        : [...request, ...schedule]
    const fingerprints = fingerprintsOf(encryptedFields, shape)
    return { current: fingerprints[0], alsoMatches: fingerprints }
}

const warnTelemetryFlushFailed = (error: unknown, invocationId: string): void => {
    logger.warn('⚠️', 'Transactional email telemetry flush failed', {
        error: error instanceof Error ? error.message : String(error),
        invocation_id: invocationId,
    })
}

type CallerChosenSender = Partial<NonNullable<AcceptedSend['from']>>

const senderTheCallerChose = (from: AcceptedSend['from']): CallerChosenSender | undefined =>
    from?.email || from?.name ? { email: from.email, name: from.name } : undefined

const writeStatus = (
    emailStatus: EmailStatusService,
    update: EmailStatusUpdate & { status: 'queued' | 'scheduled' | 'canceled' }
): void => {
    emailStatus.queue(update)
    void emailStatus.flush().catch((error) => warnTelemetryFlushFailed(error, update.messageId))
}

// The refusals that the email worker records as a skipped send when it finds the same problem. A quota limit and an
// inactive workflow are not skipped sends, because the caller can send again after it waits or fixes the workflow.
const isSkippedSendRefusal = (
    refusal: TransactionalSendRefusal
): refusal is TransactionalSendRefusal & EmailSkipReason =>
    refusal === 'sending_suspended' ||
    refusal === 'sending_paused' ||
    refusal === 'recipient_suppressed' ||
    refusal === 'recipient_unreachable'

// The intake consumer counts the queued email and writes its status once it inserts the run, so a retry counts once.
const producedResult = (
    produced: Produced,
    invocationId: string,
    scheduledAt: Date | null,
    replyFields: Record<string, number>,
    senderKind: SenderKind | undefined
): TransactionalSendResult => {
    switch (produced) {
        case 'accepted':
            return {
                outcome: 'queued',
                invocationId,
                scheduledAt: scheduledAt?.toISOString() ?? null,
                replyFields,
                senderKind,
            }
        case 'unavailable':
            return { outcome: 'intake_unavailable' }
        case 'too_large':
            return { refused: { status: 413, body: { error: 'message_too_large' } } }
        case 'invalid':
            return { outcome: 'invalid_request' }
    }
}

const scheduledAtOfRunningRow = (job: CyclotronJobInvocation): DateTime | undefined => {
    const firstScheduledAt = (job.state as CyclotronJobInvocationHogFlow['state'] | null)?.firstScheduledAt
    return firstScheduledAt ? DateTime.fromSQL(firstScheduledAt, { zone: 'utc' }) : job.queueScheduledAt
}

const recipientOf = (job: CyclotronJobInvocation): string | undefined => {
    const to = (job.state as CyclotronJobInvocationHogFlow['state'] | null)?.event?.properties?.to
    return typeof to === 'string' ? to : undefined
}

export type TransactionalSendsDeps = {
    siteUrl: string
    encryptedFields: EncryptedFields
    runIntake: RunIntake
    invocationResultsRows: HogInvocationResultsService
    emailStatus: EmailStatusService
    teamWorkflowsConfig: TeamWorkflowsConfigService
    emailSuppression: EmailSuppressionService
    emailValidation: EmailValidationService
    quotaLimiting: QuotaLimiting
    attachmentUploads: AttachmentUploads
    refuseSandboxSends: (teamId: number, recipients: string[]) => Promise<(SandboxCodeSendRefusal | null)[]>
}

export type KeyedTransactionalEmailRequest = TransactionalEmailRequest & { idempotency_key: string }

export type BatchAcceptance =
    | { refused: TransactionalSendRefusal | 'deadline_exceeded' }
    | { results: TransactionalSendResult[] }

type BatchChecks = { refusal: TransactionalSendRefusal | null; recipientRefusals: (TransactionalSendRefusal | null)[] }

// The id a keyed send's run gets, which a refusal names too, so the caller can read the send's status by it.
export const transactionalEmailRunId = (teamId: number, idempotencyKey: string): string =>
    keyedRunId(teamId, RUN_SCOPE, idempotencyKey)

export type SendFiles = {
    shape: FilesWorkflowShape | null
    sizeMessageBodies: (
        invocation: CyclotronJobInvocationHogFlow,
        emailStep: EmailStep,
        deadline: AbortSignal
    ) => Promise<MessageBodySizing>
    deadline: AbortSignal
}

export type TransactionalSendResult =
    | {
          outcome: 'queued' | 'replayed'
          invocationId: string
          scheduledAt: string | null
          replyFields: Record<string, number>
          senderKind?: SenderKind
      }
    | { outcome: TransactionalSendRefusal }
    | { refused: SendRefusal | { status: 400; body: Extract<FilesWorkflowShape, { refused: unknown }>['refused'] } }

export class TransactionalSends {
    constructor(private readonly deps: TransactionalSendsDeps) {}

    // Asked before any lookup can refuse the send, so a retry of an accepted send replays even after its workflow
    // changed. Null means no claim answers for this request.
    async recall(
        teamId: number,
        hogFlowId: string,
        request: TransactionalEmailRequest,
        stages: TransactionalEmailStageTimer,
        senderLookup: Promise<IntegrationType | null>
    ): Promise<TransactionalSendResult | null> {
        const { idempotency_key: idempotencyKey, send } = request
        const requestedAt = request.scheduled_at ? new Date(request.scheduled_at) : null
        const fingerprint = transactionalEmailFingerprint(
            this.deps.encryptedFields,
            hogFlowId,
            request,
            send,
            requestedAt
        )
        const claim = claimFor(teamId, idempotencyKey, fingerprint)
        if (!claim || !idempotencyKey) {
            return null
        }
        stages.start('idempotency')
        const isAsync = this.deps.runIntake.modeOf(teamId) === 'async'
        let recalled: Recalled
        try {
            recalled = isAsync
                ? await this.deps.runIntake.recallWithin(claim, 'transactional-email')
                : await this.deps.runIntake.recall(claim)
        } catch (error) {
            logger.error('🔑', 'Transactional email claim lookup failed', {
                error: error instanceof Error ? error.message : String(error),
            })
            return { outcome: 'idempotency_unavailable' }
        }
        if (recalled.status === 'absent') {
            return null
        }
        if (!claimedBySameRequest(fingerprint, recalled.claimedFingerprint)) {
            return { outcome: 'idempotency_key_reused' }
        }
        const stored = (recalled.reply as QueuedReply | null) ?? undefined
        // A claim made before it kept its reply falls back to what the matching request asked for.
        const scheduledAt =
            stored?.scheduledAt ??
            (requestedAt && requestedAt.getTime() > Date.now() ? requestedAt.toISOString() : null)
        const sender = !stored && send ? senderOfCodeSend(teamId, send, await senderLookup) : undefined
        const senderKind = stored ? stored.senderKind : sender?.kind === 'email_sandbox' ? sender.kind : undefined
        return {
            outcome: 'replayed',
            invocationId: recalled.runId,
            scheduledAt,
            replyFields: send?.attachments?.length ? { ...NO_ATTACHMENTS, ...stored?.replayFields } : NO_ATTACHMENTS,
            senderKind,
        }
    }

    async accept(
        team: Team,
        hogFlow: HogFlow,
        request: TransactionalEmailRequest,
        stages: TransactionalEmailStageTimer,
        files: SendFiles,
        sender: CodeSendSender = { kind: 'own' },
        settlement?: PublishSettlement
    ): Promise<TransactionalSendResult> {
        const senderKind = sender.kind === 'email_sandbox' ? sender.kind : undefined
        const { to, idempotency_key: idempotencyKey, send } = request
        const requestedAt = request.scheduled_at ? new Date(request.scheduled_at) : null

        stages.start('build')
        const invocation = this.buildInvocation(team, hogFlow, request, send, senderKind)
        const fingerprint = transactionalEmailFingerprint(
            this.deps.encryptedFields,
            hogFlow.id,
            request,
            send,
            requestedAt
        )
        const claim = claimFor(team.id, idempotencyKey, fingerprint)
        if (claim) {
            invocation.id = claim.runId
        }
        const run: Run = claim
            ? { kind: 'transactional-email', invocation, claim: { fingerprint: claim.fingerprint } }
            : { kind: 'transactional-email', invocation }
        // Async mode answers on the broker's ack and leaves the claim, the insert and the rows to the intake consumer.
        const isAsync = this.deps.runIntake.modeOf(team.id) === 'async'
        if (sender.kind === 'refused') {
            return { outcome: sender.refusal }
        }
        const latestDueAt = latestDueAtOf(invocation.id, invocation.state.event)
        const tooFarAhead = requestedAt !== null && requestedAt > latestDueAt
        const scheduledAt = !tooFarAhead && requestedAt && requestedAt.getTime() > Date.now() ? requestedAt : null
        if (scheduledAt) {
            invocation.queueScheduledAt = DateTime.fromJSDate(scheduledAt)
            invocation.state.scheduledAt = scheduledAt.toISOString()
        }
        const statusAt = new Date()
        const { shape } = files
        if (shape && 'refused' in shape) {
            return { refused: { status: 400, body: shape.refused } }
        }
        let attachmentTotals = NO_ATTACHMENTS
        let committed: Committed
        try {
            stages.start('checks')
            const recipients = transactionalEmailRecipients(request)
            const refusal = tooFarAhead
                ? 'invalid_scheduled_at'
                : isAsync
                  ? await this.refusalWithinBudget(team.id, hogFlow, recipients, senderKind)
                  : await this.refusal(team.id, hogFlow, recipients, senderKind)
            if (refusal) {
                if (isSkippedSendRefusal(refusal)) {
                    this.deps.emailStatus.queueRefusedSend({
                        teamId: team.id,
                        messageId: invocation.id,
                        recipient: to,
                        functionId: hogFlow.id,
                        reason: refusal,
                        messageCreatedAt: messageCreatedAtOf(invocation.state.event),
                    })
                    void this.deps.emailStatus.flush().catch((error) => warnTelemetryFlushFailed(error, invocation.id))
                }
                return { outcome: refusal }
            }
            if (send?.attachments?.length && shape) {
                stages.start('attachments')
                const accepted = await this.deps.attachmentUploads.acceptSend(
                    team.id,
                    send.attachments.map((ref) => ({
                        sha256: ref.sha256,
                        filename: ref.filename,
                        contentType: ref.content_type,
                        contentId: ref.content_id,
                    })),
                    (deadline) => files.sizeMessageBodies(invocation, shape.emailStep, deadline),
                    files.deadline,
                    latestDueAt
                )
                if ('refused' in accepted) {
                    return { refused: accepted.refused }
                }
                invocation.state.send = { ...invocation.state.send!, attachments: accepted.accepted.files }
                attachmentTotals = {
                    attachment_count: accepted.accepted.files.length,
                    attachment_bytes: accepted.accepted.attachmentBytes,
                }
            }
            invocation.state.statusAt = statusAt.toISOString()
            if (run.claim) {
                run.claim.reply = {
                    replayFields: attachmentTotals,
                    scheduledAt: scheduledAt?.toISOString(),
                    senderKind,
                } satisfies QueuedReply
            }
            if (isAsync) {
                stages.start('intake_produce')
                const produced = await this.deps.runIntake.produce(run, settlement)
                return producedResult(produced, invocation.id, scheduledAt, attachmentTotals, senderKind)
            }
            stages.start('queue_insert')
            committed = (await this.deps.runIntake.launch([run], { wait: 'committed', settlement }))[0]
        } catch (error) {
            if (isLockTimeout(error)) {
                return { outcome: 'idempotency_unavailable' }
            }
            throw error
        }
        if (committed.outcome === 'mismatch' && !claimedBySameRequest(fingerprint, committed.claimedFingerprint)) {
            return { outcome: 'idempotency_key_reused' }
        }
        if (committed.outcome !== 'created') {
            return {
                outcome: 'replayed',
                invocationId: committed.runId,
                scheduledAt: scheduledAt?.toISOString() ?? null,
                replyFields: attachmentTotals,
                senderKind,
            }
        }
        cdpEmailQueuedTotal.labels(PRIORITY_CLASS).inc()
        stages.start('metrics_flush')
        writeStatus(this.deps.emailStatus, {
            teamId: team.id,
            messageId: invocation.id,
            status: scheduledAt ? 'scheduled' : 'queued',
            recipient: to,
            functionId: hogFlow.id,
            scheduledAt: scheduledAt ?? undefined,
            statusAt,
            messageCreatedAt: messageCreatedAtOf(invocation.state.event),
        })
        // Best-effort rows, so the answer waits for the hand-off to Kafka (flushed on shutdown) but not the acks.
        const { produced } = await this.deps.invocationResultsRows.handOffQueuedRows()
        void produced.catch((error) => warnTelemetryFlushFailed(error, invocation.id))

        return {
            outcome: 'queued',
            invocationId: invocation.id,
            scheduledAt: scheduledAt?.toISOString() ?? null,
            replyFields: attachmentTotals,
            senderKind,
        }
    }

    // Suppression and the MX check are left to the email worker, which records a skipped send in the status read.
    async acceptBatch(
        team: Team,
        hogFlow: HogFlow,
        requests: KeyedTransactionalEmailRequest[],
        stages: TransactionalEmailStageTimer,
        sender: CodeSendSender,
        publishBy: number
    ): Promise<BatchAcceptance> {
        if (sender.kind === 'refused') {
            return { refused: sender.refusal }
        }
        const senderKind = sender.kind === 'email_sandbox' ? sender.kind : undefined
        stages.start('checks')
        const checks = await this.withinRefusalBudget(
            team.id,
            hogFlow,
            () => this.batchChecks(team.id, hogFlow, senderKind, requests),
            (quotaLimited): BatchChecks => ({
                refusal: quotaLimited ? 'quota_limited' : null,
                recipientRefusals: requests.map(() => null),
            })
        )
        if (checks.refusal) {
            return { refused: checks.refusal }
        }

        stages.start('build')
        const runs = requests.map((request) => {
            const invocation = this.buildInvocation(team, hogFlow, request, request.send, senderKind)
            const fingerprint = transactionalEmailFingerprint(
                this.deps.encryptedFields,
                hogFlow.id,
                request,
                request.send,
                null
            )
            invocation.id = transactionalEmailRunId(team.id, request.idempotency_key)
            return { invocation, fingerprint }
        })
        stages.start('idempotency')
        const recalled = await this.deps.runIntake.recallAllWithin(
            runs.map(({ invocation, fingerprint }) => ({ runId: invocation.id, fingerprint: fingerprint.current })),
            'transactional-email'
        )
        if (performance.now() > publishBy) {
            return { refused: 'deadline_exceeded' }
        }

        stages.start('intake_produce')
        const statusAt = new Date().toISOString()
        const results = await Promise.all(
            runs.map(async ({ invocation, fingerprint }, i): Promise<TransactionalSendResult> => {
                const found = recalled[i]
                if (found.status !== 'absent') {
                    if (!claimedBySameRequest(fingerprint, found.claimedFingerprint)) {
                        return { outcome: 'idempotency_key_reused' }
                    }
                    const stored = found.reply as QueuedReply | null
                    return {
                        outcome: 'replayed',
                        invocationId: found.runId,
                        scheduledAt: stored?.scheduledAt ?? null,
                        replyFields: NO_ATTACHMENTS,
                        senderKind: stored ? stored.senderKind : senderKind,
                    }
                }
                const refusal = checks.recipientRefusals[i]
                if (refusal) {
                    return { outcome: refusal }
                }
                invocation.state.statusAt = statusAt
                const reply: QueuedReply = { replayFields: NO_ATTACHMENTS, senderKind }
                const produced = await this.deps.runIntake.produce({
                    kind: 'transactional-email',
                    invocation,
                    claim: { fingerprint: fingerprint.current, reply },
                })
                return producedResult(produced, invocation.id, null, NO_ATTACHMENTS, senderKind)
            })
        )
        return { results }
    }

    private async batchChecks(
        teamId: number,
        hogFlow: HogFlow,
        senderKind: SenderKind | undefined,
        requests: KeyedTransactionalEmailRequest[]
    ): Promise<BatchChecks> {
        const whole = (refusal: TransactionalSendRefusal): BatchChecks => ({ refusal, recipientRefusals: [] })
        if (hogFlow.status !== 'active') {
            return whole('not_sendable')
        }
        if (hogFlow.email_sending_paused_at) {
            return whole('sending_paused')
        }
        const sandbox =
            senderKind === 'email_sandbox'
                ? this.deps.refuseSandboxSends(
                      teamId,
                      requests.map(({ to }) => to)
                  )
                : Promise.resolve(requests.map(() => null))
        const suspension = this.deps.teamWorkflowsConfig.getEmailSendingSuspension(teamId)
        const quota = checkHogFlowQuotaLimits(hogFlow, teamId, this.deps.quotaLimiting)
        // An earlier refusal returns before the later lookups are awaited, so their failures must not go unhandled.
        for (const lookup of [sandbox, suspension, quota] as Promise<unknown>[]) {
            lookup.catch(() => undefined)
        }
        const sandboxRefusals = await sandbox
        if (sandboxRefusals.includes('sandbox_sender_unavailable')) {
            return whole('sandbox_sender_unavailable')
        }
        if (await suspension) {
            return whole('sending_suspended')
        }
        if ((await quota).isLimited) {
            return whole('quota_limited')
        }
        return { refusal: null, recipientRefusals: sandboxRefusals }
    }

    private buildInvocation(
        team: Team,
        hogFlow: HogFlow,
        request: TransactionalEmailRequest,
        send: AcceptedSend | undefined,
        senderKind: SenderKind | undefined
    ) {
        const { to, distinct_id: distinctId, variables } = request
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
            const { attachments: _references, ...queuedSend } = send
            invocation.state.send = queuedSend
        }
        if (senderKind) {
            invocation.state.senderKind = senderKind
        }
        // The run skips the trigger pipeline that counts runs for event-triggered workflows, so the email
        // worker counts it instead.
        invocation.state.triggerMetricPending = true
        // The send's wait counts from here, so it includes any time the run spends on the intake topic.
        invocation.state.acceptedAt = new Date().toISOString()
        // Straight to the email queue: the flow's only step is the email, so a hop through the
        // workflow queue would only add latency to a password reset or a verification code.
        invocation.queue = 'email'
        invocation.queuePriority = EMAIL_QUEUE_PRIORITY[PRIORITY_CLASS]
        return invocation
    }

    private refusalWithinBudget(
        teamId: number,
        hogFlow: HogFlow,
        recipients: string[],
        senderKind: SenderKind | undefined
    ): Promise<TransactionalSendRefusal | null> {
        return this.withinRefusalBudget(
            teamId,
            hogFlow,
            () => this.refusal(teamId, hogFlow, recipients, senderKind),
            (quotaLimited) => (quotaLimited ? 'quota_limited' : null)
        )
    }

    // In async mode a slow lookup fails open, because the email worker repeats those checks before it sends. The
    // quota is the exception: the worker does not check it, so it is still checked when the others fail open.
    private async withinRefusalBudget<T>(
        teamId: number,
        hogFlow: HogFlow,
        checks: () => Promise<T>,
        failedOpen: (quotaLimited: boolean) => T
    ): Promise<T> {
        let timer: NodeJS.Timeout | undefined
        const late = new Promise<'late'>(
            (resolve) => (timer = setTimeout(() => resolve('late'), ASYNC_REFUSAL_BUDGET_MS))
        )
        try {
            const refusal = await Promise.race([checks(), late])
            if (refusal !== 'late') {
                return refusal
            }
            refusalFailOpenCounter.labels({ reason: 'late' }).inc()
        } catch (error) {
            refusalFailOpenCounter.labels({ reason: 'error' }).inc()
            logger.warn('⚠️', 'Transactional email refusal lookups failed, accepting the send', {
                team_id: teamId,
                error: error instanceof Error ? error.message : String(error),
            })
        } finally {
            clearTimeout(timer)
        }
        return failedOpen((await checkHogFlowQuotaLimits(hogFlow, teamId, this.deps.quotaLimiting)).isLimited)
    }

    // The email worker skips a send for these reasons too, but only after the caller has its answer. Checking them
    // here tells the caller that the email will not go out. The worker keeps its checks, because the state can
    // change while the job waits on the queue.
    private async refusal(
        teamId: number,
        hogFlow: HogFlow,
        recipients: string[],
        senderKind: SenderKind | undefined
    ): Promise<TransactionalSendRefusal | null> {
        if (hogFlow.status !== 'active') {
            return 'not_sendable'
        }
        if (senderKind === 'email_sandbox') {
            const [sandboxRefusal] = await this.deps.refuseSandboxSends(teamId, [recipients[0]])
            if (sandboxRefusal) {
                return sandboxRefusal
            }
        }
        // The lookups run at the same time, and the checks below await them in order, so the first refusal in that
        // order wins. The MX check's DNS lookup runs even when an earlier check refuses, which is acceptable because
        // refusals are rare and the verdict is cached per domain.
        const suspension = this.deps.teamWorkflowsConfig.getEmailSendingSuspension(teamId)
        const suppressed = Promise.all(
            recipients.map((email) =>
                this.deps.emailSuppression.isKnownSuppressed(teamId, email, { transactional: true })
            )
        )
        const quota = checkHogFlowQuotaLimits(hogFlow, teamId, this.deps.quotaLimiting)
        // A DNS failure lets the send through.
        const recipientSkipReasons = Promise.all(
            recipients.map((email) => this.deps.emailValidation.getRecipientSkipReason(teamId, email))
        )
        // An earlier refusal returns before the later lookups are awaited, so their failures must not go unhandled.
        const lookups: Promise<unknown>[] = [suspension, suppressed, quota, recipientSkipReasons]
        for (const lookup of lookups) {
            lookup.catch(() => undefined)
        }

        if (await suspension) {
            return 'sending_suspended'
        }
        if (hogFlow.email_sending_paused_at) {
            return 'sending_paused'
        }
        if ((await suppressed).some(Boolean)) {
            return 'recipient_suppressed'
        }
        if ((await quota).isLimited) {
            return 'quota_limited'
        }
        if ((await recipientSkipReasons).some(Boolean)) {
            return 'recipient_unreachable'
        }
        return null
    }
}

export type ScheduledTransactionalSendsDeps = {
    jobs: Pick<CyclotronV2JobProducer, 'cancelUnclaimed' | 'rescheduleUnclaimed'>
    hogFlows: Pick<HogFlowManagerService, 'getHogFlowCheckingPrimaryOnMiss'>
    invocationResults: Pick<InvocationResultsService, 'monitoringService' | 'invocationResultsRowsService'>
    emailStatus: EmailStatusService
    stateOpener: StateOpener
}

export type ScheduledSendCancelResult = { outcome: 'canceled' } | { outcome: 'claimed' | 'not_found' }

export type ScheduledSendRescheduleResult =
    | { outcome: 'rescheduled'; scheduledAt: string }
    | { outcome: 'invalid_scheduled_at' | 'canceled' | 'claimed' | 'not_found' }

export class ScheduledTransactionalSends {
    constructor(private readonly deps: ScheduledTransactionalSendsDeps) {}

    async cancel(teamId: number, messageId: string): Promise<ScheduledSendCancelResult> {
        if (!UUID.validateString(messageId, false)) {
            return { outcome: 'not_found' }
        }
        const result = await this.deps.jobs.cancelUnclaimed(teamId, messageId)
        switch (result.outcome) {
            case 'canceled':
                await this.recordCanceledRun(v2JobToInvocation(result.job, this.deps.stateOpener), {
                    countMetrics: true,
                })
                return { outcome: 'canceled' }
            case 'already_canceled':
                if (result.job) {
                    await this.recordCanceledRun(v2JobToInvocation(result.job, this.deps.stateOpener), {
                        countMetrics: false,
                    })
                }
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
        // A keyed id holds no time, so its bound is checked against the job's own creation, under the job's lock.
        const keyed = isKeyedMessageId(messageId)
        if (!keyed && requestedAt > now && requestedAt > latestDueAtOf(messageId)) {
            return { outcome: 'invalid_scheduled_at' }
        }
        const scheduledAt = requestedAt > now ? requestedAt : now
        const result = await this.deps.jobs.rescheduleUnclaimed(
            teamId,
            messageId,
            scheduledAt,
            keyed && requestedAt > now ? { maxAheadOfCreatedMs: MAX_SCHEDULE_AHEAD_MS } : {}
        )
        if (result.outcome === 'too_far') {
            return { outcome: 'invalid_scheduled_at' }
        }
        if (result.outcome !== 'rescheduled') {
            return { outcome: result.outcome }
        }
        const job = v2JobToInvocation(result.job, this.deps.stateOpener)
        writeStatus(this.deps.emailStatus, {
            teamId,
            messageId,
            status: 'scheduled',
            recipient: recipientOf(job),
            functionId: job.functionId,
            scheduledAt,
            statusAt: result.rescheduledAt,
            messageCreatedAt: messageCreatedAtOf(jobTriggerEvent(job)),
        })
        return { outcome: 'rescheduled', scheduledAt: scheduledAt.toISOString() }
    }

    private async recordCanceledRun(
        job: CyclotronJobInvocation,
        { countMetrics }: { countMetrics: boolean }
    ): Promise<void> {
        const { monitoringService, invocationResultsRowsService } = this.deps.invocationResults
        const hogFlow = await this.deps.hogFlows.getHogFlowCheckingPrimaryOnMiss(job.functionId).catch(() => null)
        const result = createCanceledInvocationResult(job, 'Run canceled before it was sent', hogFlow ?? undefined)
        result.invocation.queueScheduledAt = scheduledAtOfRunningRow(job)
        if (countMetrics && (job.state as CyclotronJobInvocationHogFlow['state'] | null)?.triggerMetricPending) {
            result.metrics.push({
                team_id: job.teamId,
                app_source_id: job.functionId,
                metric_kind: 'other',
                metric_name: 'triggered',
                count: 1,
            })
        }
        if (countMetrics) {
            monitoringService.queueInvocationResults([result])
        }
        invocationResultsRowsService.queueInvocationResults([result])
        writeStatus(this.deps.emailStatus, {
            teamId: job.teamId,
            messageId: job.id,
            status: 'canceled',
            recipient: recipientOf(job),
            functionId: job.functionId,
            messageCreatedAt: messageCreatedAtOf(jobTriggerEvent(job)),
        })
        void monitoringService.flush().catch((error) => warnTelemetryFlushFailed(error, job.id))
        const { produced } = await invocationResultsRowsService.handOffQueuedRows()
        void produced.catch((error) => warnTelemetryFlushFailed(error, job.id))
    }
}
