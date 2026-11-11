import { DateTime } from 'luxon'
import { z } from 'zod'

import { HogFlow } from '~/cdp/schema/hogflow'
import { InvocationResultsService } from '~/cdp/services/invocation-results.service'
import { JobQueue } from '~/cdp/services/job-queue/job-queue.interface'
import { GroupsManagerService, GroupsMap } from '~/cdp/services/managers/groups-manager.service'
import { PersonsManagerService } from '~/cdp/services/managers/persons-manager.service'
import { TeamWorkflowsConfigService } from '~/cdp/services/managers/team-workflows-config.service'
import {
    AttachmentUploads,
    MessageBodies,
    MessageBodySizing,
    SendRefusal,
} from '~/cdp/services/messaging/attachment-uploads'
import {
    EMAIL_QUEUE_PRIORITY,
    EmailQueuePriorityClass,
    cdpEmailQueuedTotal,
} from '~/cdp/services/messaging/email-priority'
import { EmailStatusService } from '~/cdp/services/messaging/email-status.service'
import { EmailSuppressionService } from '~/cdp/services/messaging/email-suppression.service'
import { EmailValidationService } from '~/cdp/services/messaging/email-validation.service'
import { utmTagsFor } from '~/cdp/services/messaging/helpers/email-html'
import { sesHtmlMaxBytes } from '~/cdp/services/messaging/helpers/ses-html-max-bytes'
import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { UTM_VALUE_LIMIT_CHARS, utmValueOverLimit } from '~/cdp/services/messaging/helpers/utm'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronPerson,
    HogFunctionInvocationGlobals,
} from '~/cdp/types'
import { throwIfDeadlinePassed } from '~/cdp/utils/deadline'
import { isHogLimitError, isHogVMError } from '~/cdp/utils/hog-error-classification'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils/hog-function-filtering'
import { EMAIL_BODY_TAG_LIMIT, countLiquidTags } from '~/cdp/utils/liquid'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'
import { PluginsServerConfig } from '~/types'

import { EmailStep, filesWorkflowShape } from './files-workflow-shape'
import { createHogFlowInvocation } from './hogflow-executor.service'
import { HogFlowFunctionsService } from './hogflow-functions.service'
import { HogFlowManagerService } from './hogflow-manager.service'
import { hogFlowPersonLookup, loadHogFlowPerson } from './hogflow-person'
import { checkHogFlowQuotaLimits } from './hogflow-quota-limiting'
import { TRANSACTIONAL_EMAIL_EVENT } from './hogflow-sensitivity'
import { IdempotencyKeys, ReplayFields } from './idempotency-keys'
import {
    AcceptedSend,
    TransactionalEmailOutcome,
    TransactionalEmailRequest,
    TransactionalEmailStageTimer,
    acceptedSendEmailFields,
    isRecipientFormatIssue,
    transactionalEmailRecipients,
} from './transactional-email'

export type TransactionalEmailDeps = {
    config: Pick<PluginsServerConfig, 'SITE_URL'>
    teamManager: TeamManager
    quotaLimiting: QuotaLimiting
    hogFlowManager: HogFlowManagerService
    hogFlowFunctionsService: HogFlowFunctionsService
    personsManager: PersonsManagerService
    groupsManager: GroupsManagerService
    idempotencyKeys: IdempotencyKeys
    attachmentUploads: AttachmentUploads
    teamWorkflowsConfigService: TeamWorkflowsConfigService
    emailSuppressionService: EmailSuppressionService
    emailValidationService: EmailValidationService
    emailTrackingCodeSigner: EmailTrackingCodeSigner
    invocationResultsService: InvocationResultsService
    emailStatusService: EmailStatusService
    hogflowQueue: JobQueue
}

export type TransactionalEmailAcceptRequest = {
    teamId: number
    hogFlowId: string
    body: unknown
    schema: z.ZodType<TransactionalEmailRequest, unknown>
}

export type TransactionalEmailAcceptClock = {
    stages: TransactionalEmailStageTimer
    // Starts when the request arrives, so the time spent before accept counts against it.
    verificationDeadline: AbortSignal
}

export type TransactionalEmailAcceptOutcome =
    | { kind: 'accepted' | 'replayed'; invocationId: string; attachmentTotals: ReplayFields }
    | { kind: 'mismatch' }
    | { kind: 'in_flight' }
    | { kind: 'unavailable' }
    | { kind: 'invalid'; message: string }
    | { kind: 'refused'; outcome: TransactionalEmailOutcome; status: number; body: Record<string, unknown> }

const refused = (
    outcome: TransactionalEmailOutcome,
    status: number,
    body: Record<string, unknown> = { error: outcome }
): TransactionalEmailAcceptOutcome => ({ kind: 'refused', outcome, status, body })

const sendRefused = ({ status, body }: SendRefusal): TransactionalEmailAcceptOutcome =>
    refused(body.error, status, body)

const NO_ATTACHMENTS = { attachment_count: 0, attachment_bytes: 0 }

const emailRenderLimitExceeded = (emailStep: EmailStep): SendRefusal => ({
    status: 400,
    body: {
        error: 'email_render_limit_exceeded',
        reason: `Rendering the "${emailStep.name}" email step went over a template limit on time or length, so the size of this email with its files could not be checked.`,
        fix: 'Simplify the template of this email step, or send this email without files.',
    },
})

const utmValueTooLong = (emailStep: EmailStep, key: string): SendRefusal => ({
    status: 400,
    body: {
        error: 'utm_value_too_long',
        reason: `The ${key} value of the "${emailStep.name}" email step is longer than ${UTM_VALUE_LIMIT_CHARS} characters, so the size of this email with its files could not be checked.`,
        fix: `Shorten the ${key} value of this email step to ${UTM_VALUE_LIMIT_CHARS} characters or fewer, or send this email without files.`,
    },
})

const emailBodyTooManyTags = (emailStep: EmailStep): SendRefusal => ({
    status: 400,
    body: {
        error: 'email_body_too_many_tags',
        reason: `The "${emailStep.name}" email step has more than ${EMAIL_BODY_TAG_LIMIT} Liquid tags, so the size of this email with its files could not be checked.`,
        fix: `Use ${EMAIL_BODY_TAG_LIMIT} Liquid tags or fewer in this email step, or send this email without files.`,
    },
})

const liquidTagsIn = (value: unknown): number => {
    if (typeof value === 'string') {
        return countLiquidTags(value)
    }
    if (value && typeof value === 'object') {
        return Object.values(value).reduce((total: number, item) => total + liquidTagsIn(item), 0)
    }
    return 0
}

const liquidTagsInStep = (emailStep: EmailStep): number =>
    Object.entries(emailStep.config.inputs).reduce((total: number, [key, input]) => {
        if (input?.templating !== 'liquid') {
            return total
        }
        const rendered =
            key === 'email' && input.value && typeof input.value === 'object'
                ? { ...input.value, design: undefined }
                : input.value
        return total + liquidTagsIn(rendered)
    }, 0)

const ACCEPTED_SEND_FINGERPRINT_MARKER = 'accepted_send'

const transactionalEmailFingerprint = (
    hogFlowId: string,
    { to, distinct_id, variables }: TransactionalEmailRequest,
    send: AcceptedSend | undefined
): string => {
    const templateRequest = [hogFlowId, to, distinct_id, variables]
    return IdempotencyKeys.fingerprint(
        send ? [...templateRequest, ACCEPTED_SEND_FINGERPRINT_MARKER, withSenderTheCallerChose(send)] : templateRequest
    )
}

type CallerChosenSender = Partial<NonNullable<AcceptedSend['from']>>

type WorkerRenderContext = { person: CyclotronPerson | undefined; groups: GroupsMap }

const withSenderTheCallerChose = ({
    from,
    ...send
}: AcceptedSend): Omit<AcceptedSend, 'from'> & { from?: CallerChosenSender } => ({
    ...send,
    from: senderTheCallerChose(from),
})

const senderTheCallerChose = (from: AcceptedSend['from']): CallerChosenSender | undefined => {
    if (!from) {
        return undefined
    }
    return from.email ? { email: from.email, name: from.name } : { integrationId: from.integrationId, name: from.name }
}

const sendBodies = (invocation: CyclotronJobInvocationHogFlow): MessageBodies => {
    const sendFields = acceptedSendEmailFields(invocation.state.send)
    return {
        bodyBytes: [sendFields.html ?? '', sendFields.text ?? ''].map((body) => Buffer.byteLength(body)),
        subject: sendFields.subject ?? '',
    }
}

export class TransactionalEmail {
    constructor(private readonly deps: TransactionalEmailDeps) {}

    async accept(
        { teamId, hogFlowId, body, schema }: TransactionalEmailAcceptRequest,
        { stages, verificationDeadline }: TransactionalEmailAcceptClock
    ): Promise<TransactionalEmailAcceptOutcome> {
        stages.start('validate')
        const parsed = schema.safeParse(body)
        if (!parsed.success) {
            const issues = parsed.error.issues
            // Signup accepts some addresses this check refuses, and no retry can fix an address.
            if (issues.every(isRecipientFormatIssue)) {
                return refused('recipient_unreachable', 422)
            }
            // Paths and codes only: the values include the recipient's address.
            logger.warn('⚠️', 'Transactional email request failed validation', {
                team_id: teamId,
                hog_flow_id: hogFlowId,
                issues: issues.map((issue) => ({ path: issue.path.join('.'), code: issue.code })),
            })
            return { kind: 'invalid', message: parsed.error.message }
        }
        const { to, distinct_id: distinctId, variables, idempotency_key: idempotencyKey, send } = parsed.data
        const references = send?.attachments ?? []
        if (references.length > 0 && !this.deps.attachmentUploads.isAllowed(teamId)) {
            return refused('field_not_accepted', 400)
        }

        stages.start('load')
        const teamLookup = this.deps.teamManager.getTeam(teamId).catch(() => null)
        const hogFlowLookup = this.deps.hogFlowManager.getHogFlowCheckingPrimaryOnMiss(hogFlowId)
        // A missing team returns before the workflow lookup is awaited, so its failure must not go unhandled.
        hogFlowLookup.catch(() => undefined)
        const team = await teamLookup
        if (!team) {
            return refused('not_found', 404, { error: 'Team not found' })
        }
        const hogFlow = await hogFlowLookup
        if (!hogFlow || hogFlow.team_id !== team.id) {
            return refused('not_found', 404, { error: 'Workflow not found' })
        }
        if (hogFlow.trigger?.type !== 'api') {
            return refused('not_sendable', 400)
        }
        const filesShape = references.length > 0 ? filesWorkflowShape(hogFlow) : null

        stages.start('build')
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
                url: `${this.deps.config.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`,
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
        // The run skips the trigger pipeline that counts runs for event-triggered workflows, so the email
        // worker counts it instead.
        invocation.state.triggerMetricPending = true
        // Straight to the email queue: the flow's only step is the email, so a hop through the
        // workflow queue would only add latency to a password reset or a verification code.
        const priorityClass: EmailQueuePriorityClass = 'fast'
        invocation.queue = 'email'
        invocation.queuePriority = EMAIL_QUEUE_PRIORITY[priorityClass]

        const idempotencyKeys = this.deps.idempotencyKeys
        const fingerprint = transactionalEmailFingerprint(hogFlow.id, parsed.data, send)
        const releaseKey = async () => {
            if (idempotencyKey) {
                stages.start('idempotency')
                await idempotencyKeys.release(team.id, idempotencyKey, invocation.id)
            }
        }
        if (idempotencyKey) {
            stages.start('idempotency')
            const reservation = await idempotencyKeys.reserve(team.id, idempotencyKey, fingerprint, invocation.id)
            switch (reservation.status) {
                case 'replayed':
                    return {
                        kind: 'replayed',
                        invocationId: reservation.invocationId,
                        attachmentTotals: { ...NO_ATTACHMENTS, ...reservation.replayFields },
                    }
                case 'in_flight':
                    return { kind: 'in_flight' }
                case 'conflict':
                    return { kind: 'mismatch' }
                case 'unavailable':
                    return { kind: 'unavailable' }
            }
        }
        if (filesShape && 'refused' in filesShape) {
            await releaseKey()
            return refused(filesShape.refused.error, 400, filesShape.refused)
        }
        let attachmentTotals = NO_ATTACHMENTS
        try {
            stages.start('checks')
            const refusal = await this.refuseTransactionalEmail(
                team.id,
                hogFlow,
                transactionalEmailRecipients(parsed.data)
            )
            if (refusal) {
                await releaseKey()
                return refused(refusal.outcome, refusal.status)
            }
            if (send && filesShape) {
                stages.start('attachments')
                const files = await this.deps.attachmentUploads.acceptSend(
                    team.id,
                    references.map((ref) => ({
                        sha256: ref.sha256,
                        filename: ref.filename,
                        contentType: ref.content_type,
                        contentId: ref.content_id,
                    })),
                    (deadline) => this.messageBodyBytes(hogFlow, invocation, filesShape.emailStep, deadline),
                    verificationDeadline
                )
                if ('refused' in files) {
                    await releaseKey()
                    return sendRefused(files.refused)
                }
                invocation.state.send = { ...invocation.state.send!, attachments: files.accepted.files }
                attachmentTotals = {
                    attachment_count: files.accepted.files.length,
                    attachment_bytes: files.accepted.attachmentBytes,
                }
            }
            stages.start('queue_insert')
            this.deps.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
            try {
                await this.deps.hogflowQueue.queueInvocations([invocation])
            } catch (error) {
                this.deps.invocationResultsService.invocationResultsRowsService.dropQueuedRowsFor([invocation.id])
                throw error
            }
            cdpEmailQueuedTotal.labels(priorityClass).inc()
        } catch (error) {
            await releaseKey()
            throw error
        }
        if (idempotencyKey) {
            stages.start('idempotency')
            await idempotencyKeys.markQueued(team.id, idempotencyKey, fingerprint, invocation.id, attachmentTotals)
        }
        stages.start('metrics_flush')
        this.deps.emailStatusService.queue({
            teamId: team.id,
            messageId: invocation.id,
            status: 'queued',
            recipient: to,
            functionId: hogFlow.id,
        })
        // Best-effort rows, so the 202 waits for the hand-off to Kafka (flushed on shutdown) but not the acks.
        const warnTelemetryFlushFailed = (error: unknown) =>
            logger.warn('⚠️', 'Transactional email telemetry flush failed', {
                error: error instanceof Error ? error.message : String(error),
                invocation_id: invocation.id,
            })
        void this.deps.emailStatusService.flush().catch(warnTelemetryFlushFailed)
        const { produced } = await this.deps.invocationResultsService.invocationResultsRowsService.handOffQueuedRows()
        void produced.catch(warnTelemetryFlushFailed)

        return { kind: 'accepted', invocationId: invocation.id, attachmentTotals }
    }

    private async messageBodyBytes(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow,
        emailStep: EmailStep,
        deadline: AbortSignal
    ): Promise<MessageBodySizing> {
        const longUtmValue = emailStep.config.utm_tags_enabled
            ? utmValueOverLimit(emailStep.config.utm_params)
            : undefined
        if (longUtmValue) {
            return { refused: utmValueTooLong(emailStep, longUtmValue) }
        }
        if (liquidTagsInStep(emailStep) > EMAIL_BODY_TAG_LIMIT) {
            return { refused: emailBodyTooManyTags(emailStep) }
        }
        const renderContext = await this.workerRenderContext(hogFlow, invocation)
        deadline.throwIfAborted()
        try {
            return await this.emailStepBodies(hogFlow, invocation, emailStep, renderContext, deadline)
        } catch (error) {
            if (isHogLimitError(error)) {
                return { refused: emailRenderLimitExceeded(emailStep) }
            }
            if (!isHogVMError(error)) {
                throw error
            }
            logger.warn('⚠️', 'Could not render the email step of a send with files', {
                team_id: hogFlow.team_id,
                hog_flow_id: hogFlow.id,
                error: error instanceof Error ? error.name : 'UnknownError',
            })
            return sendBodies(invocation)
        }
    }

    private async workerRenderContext(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<WorkerRenderContext> {
        const [person, groups] = await Promise.all([
            this.recipientPerson(hogFlow, invocation),
            this.deps.groupsManager.getGroupsForEvent(
                hogFlow.team_id,
                invocation.state.event.properties ?? {},
                `${this.deps.config.SITE_URL}/project/${hogFlow.team_id}`
            ),
        ])
        return { person, groups }
    }

    private async recipientPerson(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronPerson | undefined> {
        const lookup = hogFlowPersonLookup(hogFlow, invocation.state)
        return lookup ? await loadHogFlowPerson(this.deps.personsManager, hogFlow, lookup) : undefined
    }

    private async emailStepBodies(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow,
        step: EmailStep,
        { person, groups }: WorkerRenderContext,
        deadline: AbortSignal
    ): Promise<MessageBodies> {
        const hogFunction = await this.deps.hogFlowFunctionsService.buildHogFunction(hogFlow, step.config, step.name)
        deadline.throwIfAborted()
        const atEmailStep = {
            ...invocation,
            state: { ...invocation.state, currentAction: { id: step.id, startedAtTimestamp: Date.now() } },
        }
        const rendered = await this.deps.hogFlowFunctionsService.buildHogFunctionInvocation(
            atEmailStep,
            hogFunction,
            { event: invocation.state.event, person, groups, variables: invocation.state.variables },
            deadline
        )
        deadline.throwIfAborted()
        const email = { ...rendered.state.globals.inputs?.email, ...acceptedSendEmailFields(invocation.state.send) }
        return {
            bodyBytes: [
                typeof email.html === 'string' && email.html
                    ? this.sesHtmlMaxBytes(rendered, email.html, email.preheader, deadline)
                    : 0,
                typeof email.text === 'string' ? Buffer.byteLength(email.text) : 0,
            ],
            subject: typeof email.subject === 'string' ? email.subject : '',
        }
    }

    private sesHtmlMaxBytes(
        rendered: CyclotronJobInvocationHogFunction,
        html: string,
        preheader: unknown,
        deadline: AbortSignal
    ): number {
        const utmTags = utmTagsFor(rendered, () => undefined, deadline)
        throwIfDeadlinePassed(deadline)
        return sesHtmlMaxBytes(html, {
            utmTags,
            invocation: rendered,
            signer: this.deps.emailTrackingCodeSigner,
            preheader: typeof preheader === 'string' ? preheader : undefined,
        })
    }

    // The email worker skips a send for these reasons too, but only after the caller has its 202. Checking them
    // here tells the caller that the email will not go out. The worker keeps its checks, because the state can
    // change while the job waits on the queue.
    private async refuseTransactionalEmail(
        teamId: number,
        hogFlow: HogFlow,
        recipients: string[]
    ): Promise<{ outcome: TransactionalEmailOutcome; status: number } | null> {
        if (hogFlow.status !== 'active') {
            return { outcome: 'not_sendable', status: 400 }
        }
        // The lookups run at the same time, and the checks below await them in order, so the first refusal in that
        // order wins. The MX check's DNS lookup runs even when an earlier check refuses, which is acceptable because
        // refusals are rare and the verdict is cached per domain.
        const suspension = this.deps.teamWorkflowsConfigService.getEmailSendingSuspension(teamId)
        const suppressed = Promise.all(
            recipients.map((email) =>
                this.deps.emailSuppressionService.isKnownSuppressed(teamId, email, { transactional: true })
            )
        )
        const quota = checkHogFlowQuotaLimits(hogFlow, teamId, this.deps.quotaLimiting)
        // A DNS failure lets the send through.
        const recipientSkipReasons = Promise.all(
            recipients.map((email) => this.deps.emailValidationService.getRecipientSkipReason(teamId, email))
        )
        // An earlier refusal returns before the later lookups are awaited, so their failures must not go unhandled.
        const lookups: Promise<unknown>[] = [suspension, suppressed, quota, recipientSkipReasons]
        for (const lookup of lookups) {
            lookup.catch(() => undefined)
        }

        if (await suspension) {
            return { outcome: 'sending_suspended', status: 422 }
        }
        if (hogFlow.email_sending_paused_at) {
            return { outcome: 'sending_paused', status: 422 }
        }
        if ((await suppressed).some(Boolean)) {
            return { outcome: 'recipient_suppressed', status: 422 }
        }
        if ((await quota).isLimited) {
            return { outcome: 'quota_limited', status: 429 }
        }
        if ((await recipientSkipReasons).some(Boolean)) {
            return { outcome: 'recipient_unreachable', status: 422 }
        }
        return null
    }
}
