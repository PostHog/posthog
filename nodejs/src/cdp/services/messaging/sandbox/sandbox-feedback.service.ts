import addressparser from 'nodemailer/lib/addressparser'
import { Counter } from 'prom-client'
import { ZodError } from 'zod'

import { MinimalAppMetric } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { Team } from '~/types'

import { HogFunctionMonitoringService } from '../../monitoring/hog-function-monitoring.service'
import { EmailSuppressionService } from '../email-suppression.service'
import { BOUNCE_TYPE_TO_EVENT_PROPERTY, nonexistentRecipients, sentToRecipients } from '../helpers/ses'
import { SesEventRecord } from '../helpers/ses-events'
import { SnsEnvelopeVerifier } from '../helpers/sns-envelope'

export const SANDBOX_SES_TAGS = {
    team: 'ph_sbx_team',
    flow: 'ph_sbx_flow',
    run: 'ph_sbx_run',
    action: 'ph_sbx_action',
    version: 'ph_sbx_version',
    test: 'ph_sbx_test',
    parentRun: 'ph_sbx_parent_run',
} as const

export type SandboxFeedbackAttribution = {
    teamId: number
    hogFlowId: string
    invocationId: string
    actionId: string
    flowVersion: number
    isTest: boolean
    parentRunId?: string
}

type SandboxFeedbackKind = 'delivered' | 'bounced' | 'complained'

type SandboxFeedback = {
    attribution: SandboxFeedbackAttribution
    kind: SandboxFeedbackKind
    bounceType?: 'hard' | 'soft' | 'unknown'
}

type SandboxFeedbackConfig = {
    SES_SANDBOX_ALLOWED_SNS_TOPIC_ARNS: string
    SES_SANDBOX_FROM_ADDRESS: string
}

type SuppressionWriter = Pick<
    EmailSuppressionService,
    'recordDeliveries' | 'recordHardBounces' | 'recordGlobalHardBounces' | 'recordTransientBounces' | 'recordComplaints'
>

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const POSITIVE_INTEGER = /^[1-9][0-9]{0,15}$/
const NON_NEGATIVE_INTEGER = /^(0|[1-9][0-9]{0,15})$/
const ACTION_ID = /^[A-Za-z0-9_-]{1,128}$/

const FEEDBACK_METRIC_NAME: Record<SandboxFeedbackKind, MinimalAppMetric['metric_name']> = {
    delivered: 'email_sandbox_delivered',
    bounced: 'email_sandbox_bounced',
    complained: 'email_sandbox_complained',
}

const feedbackCounter = new Counter({
    name: 'cdp_sandbox_email_feedback_total',
    help: 'SES feedback records on the sandbox webhook, by what the webhook did with them',
    labelNames: ['event_type', 'outcome'],
})

const unattributedFeedbackCounter = new Counter({
    name: 'cdp_sandbox_email_feedback_unattributed_total',
    help: 'Sandbox SES feedback records acknowledged without processing because their tags did not parse',
    labelNames: ['event_type'],
})

const singleTag = (tags: Record<string, string[]> | undefined, name: string): string | null => {
    const values = tags?.[name]
    return values?.length === 1 ? values[0] : null
}

export function parseSandboxTags(tags: Record<string, string[]> | undefined): SandboxFeedbackAttribution | null {
    const team = singleTag(tags, SANDBOX_SES_TAGS.team)
    const flow = singleTag(tags, SANDBOX_SES_TAGS.flow)
    const run = singleTag(tags, SANDBOX_SES_TAGS.run)
    const action = singleTag(tags, SANDBOX_SES_TAGS.action)
    const version = singleTag(tags, SANDBOX_SES_TAGS.version)
    const test = singleTag(tags, SANDBOX_SES_TAGS.test)
    const hasParentRun = tags?.[SANDBOX_SES_TAGS.parentRun] !== undefined
    const parentRun = singleTag(tags, SANDBOX_SES_TAGS.parentRun)
    if (hasParentRun && (parentRun === null || !ACTION_ID.test(parentRun))) {
        return null
    }
    if (
        team === null ||
        !POSITIVE_INTEGER.test(team) ||
        flow === null ||
        !UUID.test(flow) ||
        run === null ||
        !UUID.test(run) ||
        action === null ||
        !ACTION_ID.test(action) ||
        version === null ||
        !NON_NEGATIVE_INTEGER.test(version) ||
        (test !== 'true' && test !== 'false')
    ) {
        return null
    }
    return {
        teamId: Number(team),
        hogFlowId: flow,
        invocationId: run,
        actionId: action,
        flowVersion: Number(version),
        isTest: test === 'true',
        ...(parentRun ? { parentRunId: parentRun } : {}),
    }
}

const withdrawsEarlierComplaint = (feedbackType: string | undefined): boolean =>
    feedbackType?.toLowerCase() === 'not-spam'

const asRecipients = (addresses: string[]): { emailAddress: string }[] =>
    addresses.map((emailAddress) => ({ emailAddress }))

export class SandboxFeedbackService {
    private verifier: SnsEnvelopeVerifier | null
    private fromAddress: string

    constructor(
        config: SandboxFeedbackConfig,
        private suppression: SuppressionWriter,
        private monitoring: Pick<HogFunctionMonitoringService, 'queueAppMetric' | 'flush'>,
        private teamManager: { getTeam(teamId: number): Promise<Team | null> },
        private capture: typeof captureTeamEvent = captureTeamEvent
    ) {
        const allowedTopicArns = config.SES_SANDBOX_ALLOWED_SNS_TOPIC_ARNS.split(',')
            .map((arn) => arn.trim())
            .filter(Boolean)
        this.verifier = allowedTopicArns.length > 0 ? new SnsEnvelopeVerifier(allowedTopicArns) : null
        this.fromAddress = config.SES_SANDBOX_FROM_ADDRESS.trim().toLowerCase()
    }

    public async handle(req: { body?: unknown }): Promise<{ status: number; message?: string }> {
        if (!this.verifier || !this.fromAddress) {
            return { status: 503, message: 'Sandbox email feedback is not configured' }
        }
        if (typeof req.body !== 'string' || req.body === '') {
            return { status: 400, message: 'Missing request body' }
        }

        let verdict: Awaited<ReturnType<SnsEnvelopeVerifier['verify']>>
        try {
            verdict = await this.verifier.verify(parseJSON(req.body), { verifySignature: true })
        } catch (error) {
            if (error instanceof SyntaxError || error instanceof ZodError) {
                return { status: 400, message: 'Invalid SNS message' }
            }
            throw error
        }
        if (verdict.kind === 'reject' && verdict.certificateUnavailable) {
            return { status: 503, message: 'SNS signing certificate unavailable' }
        }
        if (verdict.kind === 'reject') {
            return { status: verdict.status, message: verdict.error }
        }
        if (verdict.kind === 'ack') {
            return { status: 200 }
        }

        const feedback: SandboxFeedback[] = []
        try {
            for (const record of verdict.records) {
                const recorded = await this.recordFeedback(record)
                if (recorded) {
                    feedback.push(recorded)
                }
            }
        } catch (error) {
            logger.error('[SandboxFeedbackService] Failed to update the suppression list', { error })
            return { status: 500, message: 'Suppression update failed' }
        }

        this.reportWithoutDelayingTheAnswer(feedback)
        return { status: 200 }
    }

    private async recordFeedback(record: SesEventRecord): Promise<SandboxFeedback | null> {
        const count = (outcome: string): void => feedbackCounter.inc({ event_type: record.eventType, outcome })

        if (!this.isSandboxSender(record.mail.source)) {
            count('other_sender')
            return null
        }
        const attribution = parseSandboxTags(record.mail.tags)
        if (!attribution) {
            unattributedFeedbackCounter.inc({ event_type: record.eventType })
            return null
        }

        const { teamId, isTest } = attribution
        const strict = { throwOnFailure: true }
        switch (record.eventType) {
            case 'Delivery': {
                const delivered = sentToRecipients(
                    record,
                    asRecipients(record.delivery.recipients ?? record.mail.destination)
                )
                if (delivered.length === 0) {
                    count('not_sent_to')
                    return null
                }
                if (!isTest) {
                    await this.suppression.recordDeliveries(
                        teamId,
                        delivered.map((r) => r.emailAddress),
                        record.delivery.timestamp,
                        { clearGlobal: true, ...strict }
                    )
                }
                count('processed')
                return { attribution, kind: 'delivered' }
            }
            case 'Bounce': {
                const bounced = sentToRecipients(record, record.bounce.bouncedRecipients)
                if (bounced.length === 0) {
                    count('not_sent_to')
                    return null
                }
                const addresses = bounced.map((r) => r.emailAddress)
                const diagnostic = bounced.find((r) => r.diagnosticCode)?.diagnosticCode
                if (!isTest && record.bounce.bounceType === 'Permanent') {
                    await this.suppression.recordHardBounces(teamId, addresses, diagnostic, strict)
                    const nonexistent = nonexistentRecipients({ ...record.bounce, bouncedRecipients: bounced })
                    if (nonexistent.length > 0) {
                        await this.suppression.recordGlobalHardBounces(nonexistent, record.bounce.timestamp, strict)
                    }
                } else if (!isTest && record.bounce.bounceType === 'Transient') {
                    await this.suppression.recordTransientBounces(
                        teamId,
                        addresses,
                        diagnostic,
                        record.bounce.timestamp,
                        strict
                    )
                }
                count('processed')
                return {
                    attribution,
                    kind: 'bounced',
                    bounceType: BOUNCE_TYPE_TO_EVENT_PROPERTY[record.bounce.bounceType],
                }
            }
            case 'Complaint': {
                if (withdrawsEarlierComplaint(record.complaint.complaintFeedbackType)) {
                    count('not_spam')
                    return null
                }
                const complained = sentToRecipients(record, record.complaint.complainedRecipients)
                if (complained.length === 0) {
                    count('not_sent_to')
                    return null
                }
                if (!isTest) {
                    await this.suppression.recordComplaints(
                        teamId,
                        complained.map((r) => r.emailAddress),
                        record.complaint.complaintFeedbackType,
                        strict
                    )
                }
                count('processed')
                return { attribution, kind: 'complained' }
            }
            default:
                count('unsupported_event')
                return null
        }
    }

    private isSandboxSender(source: string): boolean {
        const addresses = addressparser(source, { flatten: true })
        return addresses.length === 1 && addresses[0].address.trim().toLowerCase() === this.fromAddress
    }

    private reportWithoutDelayingTheAnswer(feedback: SandboxFeedback[]): void {
        for (const item of feedback) {
            this.queueMetric(item)
        }
        void this.monitoring.flush().catch((error) => {
            logger.warn('[SandboxFeedbackService] Failed to flush sandbox email feedback metrics', { error })
        })
        void this.captureEvents(feedback)
    }

    private queueMetric({ attribution, kind }: SandboxFeedback): void {
        const { teamId, hogFlowId, actionId, flowVersion, isTest, parentRunId } = attribution
        if (isTest) {
            return
        }
        try {
            this.monitoring.queueAppMetric(
                {
                    team_id: teamId,
                    app_source_id: parentRunId ?? hogFlowId,
                    instance_id: actionId,
                    metric_kind: 'email',
                    metric_name: FEEDBACK_METRIC_NAME[kind],
                    count: 1,
                    app_source_version: { id: hogFlowId, version: flowVersion },
                },
                'hog_flow'
            )
        } catch (error) {
            logger.warn('[SandboxFeedbackService] Failed to queue a sandbox email feedback metric', { teamId, error })
        }
    }

    private async captureEvents(feedback: SandboxFeedback[]): Promise<void> {
        for (const { attribution, kind, bounceType } of feedback) {
            const { teamId, hogFlowId, actionId, isTest } = attribution
            try {
                const team = await this.teamManager.getTeam(teamId)
                if (team) {
                    this.capture(team, `workflows sandbox email ${kind}`, {
                        workflow_id: hogFlowId,
                        action_id: actionId,
                        is_test: isTest,
                        ...(bounceType ? { bounce_type: bounceType } : {}),
                    })
                }
            } catch (error) {
                logger.warn('[SandboxFeedbackService] Failed to capture a sandbox email feedback event', {
                    teamId,
                    error,
                })
            }
        }
    }
}
