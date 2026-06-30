import { MessageHeader, SESv2Client, SendEmailCommand, SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { DateTime } from 'luxon'
import { SendMailOptions } from 'nodemailer'
import { Counter } from 'prom-client'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '~/cdp/types'
import { createAddLogFunction, logEntry } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'

import { IntegrationManagerService } from '../managers/integration-manager.service'
import { RecipientManagerRecipient } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { addTrackingToEmail, resolveEmailEngagementDistinctId } from './email-tracking.service'
import { mailDevTransport, mailDevWebUrl } from './helpers/maildev'
import { maybeAddPreheaderToEmail } from './helpers/preheader'
import { EmailTrackingCodeSigner, TRACKING_CODE_HEADER_NAME } from './helpers/tracking-code'
import { RecipientTokensService } from './recipient-tokens.service'

const sesThrottleResponsesTotal = new Counter({
    name: 'cdp_ses_throttle_responses_total',
    help: 'SES API responses classified as throttle/rate-limit. Sustained nonzero rate means the local bucket is set too high vs. the SES quota.',
    labelNames: ['error_code'],
})

/**
 * SES error codes that signal a transient rate-limit shape — safe to retry
 * shortly after. `TooManyRequestsException` is the SES-v2-specific class;
 * `ThrottlingException` is a generic AWS SDK error code that can surface
 * from the underlying transport layer for the same condition (not exported
 * as a class for sesv2, so we match by `name`).
 *
 * `SendingPausedException` is *not* on this list — it signals a reputation
 * or account-state problem that won't recover in seconds. Retrying within
 * 500ms just burns reschedules; the job hard-fails instead, surfaces via
 * `email_failed`, and the underlying SES config needs operator attention.
 */
const SES_THROTTLE_ERROR_NAMES = ['TooManyRequestsException', 'ThrottlingException'] as const
type SesThrottleErrorName = (typeof SES_THROTTLE_ERROR_NAMES)[number]

function isSesThrottleError(error: unknown): error is Error & { name: SesThrottleErrorName } {
    return error instanceof Error && (SES_THROTTLE_ERROR_NAMES as readonly string[]).includes(error.name)
}

/**
 * Tagged error signalling that SES rejected the send for a transient,
 * rate-limit-shaped reason. The caller schedules a retry instead of failing
 * the job. Carries the SES error name for metrics and the retry delay we
 * pick locally (SES doesn't return a Retry-After header).
 */
export class SESThrottleError extends Error {
    public readonly errorCode: SesThrottleErrorName
    public readonly retryAfterMs: number

    constructor(errorCode: SesThrottleErrorName, retryAfterMs: number, message: string) {
        super(message)
        this.name = 'SESThrottleError'
        this.errorCode = errorCode
        this.retryAfterMs = retryAfterMs
    }
}

function pickThrottleRetryDelayMs(): number {
    // Constant 500–1000ms jitter is plenty: the local Valkey bucket already
    // gates re-dequeue at the configured refill rate, so a quick retry will
    // simply re-claim a token if SES capacity has refreshed. Exponential
    // backoff isn't needed at this layer.
    return 500 + Math.floor(Math.random() * 500)
}

export interface EmailServiceConfig {
    sesAccessKeyId: string
    sesSecretAccessKey: string
    sesRegion: string
    sesEndpoint: string
}

/**
 * Strips control characters from an email subject to prevent header injection
 * and delivery issues. Removes ASCII 0-31 (except horizontal tab) and DEL (127).
 */
export function sanitizeEmailSubject(subject: string): string {
    return subject
        .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
        .replace(/[\r\n]+/g, ' ')
        .trim()
}

export function parseAddressList(value?: string): string[] | undefined {
    if (!value || !value.trim()) {
        return undefined
    }
    const result = value
        .split(',')
        .map((addr) => addr.trim())
        .filter((addr) => addr.length > 0)
    return result.length > 0 ? result : undefined
}

export class EmailService {
    sesV2Client: SESv2Client | null

    private recipientTokensService: RecipientTokensService

    constructor(
        private sesConfig: EmailServiceConfig,
        private integrationManager: IntegrationManagerService,
        private teamWorkflowsConfigService: TeamWorkflowsConfigService,
        encryptionSaltKeys: string,
        siteUrl: string,
        private trackingCodeSigner: EmailTrackingCodeSigner
    ) {
        this.sesV2Client = this.sesConfig.sesRegion
            ? new SESv2Client({
                  region: this.sesConfig.sesRegion,
                  endpoint: this.sesConfig.sesEndpoint || undefined,
              })
            : null
        this.recipientTokensService = new RecipientTokensService(encryptionSaltKeys, siteUrl)
    }

    // Send email. `isTest` flags sends from the editor's "Run test" path so the tracking code
    // embedded in the email tells the SES webhook to skip recording metrics for test traffic.
    public async executeSendEmail(
        invocation: CyclotronJobInvocationHogFunction,
        isTest = false
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        if (invocation.queueParameters?.type !== 'email') {
            throw new Error('Invocation passed to sendEmail is not an email function')
        }

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(
            invocation,
            {},
            {
                finished: true,
            }
        )
        const addLog = createAddLogFunction(result.logs)

        const params = invocation.queueParameters
        const integration = await this.integrationManager.get(params.from.integrationId)

        let success: boolean = false
        let throttled: boolean = false

        try {
            // Wrong-team references deliberately read as not-found so an ID's existence on another team can't be probed
            if (!integration || integration.team_id !== invocation.teamId) {
                throw new Error(
                    "Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step."
                )
            }
            if (integration.kind !== 'email') {
                throw new Error(
                    "The integration configured for this step is not an email channel — select an email sender in the workflow's email step."
                )
            }

            const from = this.resolveFromSender(integration)

            switch (integration.config.provider ?? 'ses') {
                case 'maildev':
                    await this.sendEmailWithMaildev(result, params, from, isTest)
                    break
                case 'ses':
                    await this.sendEmailWithSES(result, params, from, isTest)
                    break

                case 'unsupported':
                    throw new Error('Email delivery mode not supported')
            }

            addLog('info', `Email sent to ${params.to.email}`)
            success = true
        } catch (error) {
            if (error instanceof SESThrottleError) {
                // Treat as a transient delivery delay — reschedule rather than fail
                // the job. Our local bucket is the primary throttle; this path
                // catches the cases where SES disagrees with our estimate.
                throttled = true
                result.finished = false
                result.invocation.queueScheduledAt = DateTime.utc().plus({ milliseconds: error.retryAfterMs })
                addLog('warn', `SES rate-limited (${error.errorCode}); rescheduling email in ${error.retryAfterMs}ms`)
            } else {
                addLog('error', error.message)
                result.error = error.message
                result.finished = true
            }
        }

        if (throttled) {
            // On throttle, skip both the VM-state push and the business-metric
            // emit. The eventual successful retry will produce `email_sent` and
            // push the success bit to the VM stack — pushing them now would
            // double-count and lie about the send outcome.
            return result
        }

        // Push the response to the VM stack if running inline (not from the email queue)
        result.invocation.state.vmState?.stack.push({
            success,
        })

        // Test sends (from the editor's "Run test") must not record metrics — keep them out of the
        // workflow's Metrics tab, mirroring the isTest skip the SES webhook applies to delivery/open/click.
        if (!isTest) {
            result.metrics.push({
                team_id: invocation.teamId,
                app_source_id: invocation.parentRunId ?? invocation.functionId,
                instance_id: invocation.state.actionId || invocation.id,
                metric_kind: 'email',
                metric_name: success ? 'email_sent' : 'email_failed',
                count: 1,
            })
        }

        const distinctId = resolveEmailEngagementDistinctId(invocation)
        if (
            distinctId &&
            !isTest &&
            (await this.teamWorkflowsConfigService.shouldCaptureEngagementEvents(invocation.teamId))
        ) {
            result.capturedPostHogEvents.push({
                team_id: invocation.teamId,
                timestamp: new Date().toISOString(),
                distinct_id: distinctId,
                event: success ? '$workflows_email_sent' : '$workflows_email_failed',
                properties: {
                    $workflow_id: invocation.functionId,
                    $workflow_action_id: invocation.state.actionId,
                    $email_to: params.to.email,
                    $email_subject: params.subject,
                },
            })
        }

        return result
    }

    private resolveFromSender(integration: IntegrationType): { email: string; name: string } {
        if (!integration.config.verified) {
            throw new Error('The selected email integration domain is not verified')
        }

        if (!integration.config.email || !integration.config.name) {
            throw new Error('The selected email integration is not configured correctly')
        }

        return { email: integration.config.email, name: integration.config.name }
    }

    // Send email to local maildev instance for testing (DEBUG=1 only)
    private async sendEmailWithMaildev(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType,
        from: { email: string; name: string },
        isTest = false
    ): Promise<void> {
        // This can timeout but there is no native timeout so we do our own one
        const mailOptions: SendMailOptions = {
            from: from.name ? `"${from.name}" <${from.email}>` : from.email,
            to: params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email,
            subject: sanitizeEmailSubject(params.subject),
            text: params.text,
            ...(params.html
                ? { html: addTrackingToEmail(params.html, result.invocation, this.trackingCodeSigner, isTest) }
                : {}),
        }

        const ccAddresses = parseAddressList(params.cc)
        const bccAddresses = parseAddressList(params.bcc)

        if (ccAddresses) {
            mailOptions.cc = ccAddresses
        }
        if (bccAddresses) {
            mailOptions.bcc = bccAddresses
        }

        const response = await mailDevTransport!.sendMail(mailOptions)

        if (!response.accepted) {
            throw new Error(`Failed to send email to maildev: ${JSON.stringify(response)}`)
        }

        result.logs.push(logEntry('debug', `Email sent to your local maildev server: ${mailDevWebUrl}`))
    }

    private async sendEmailWithSES(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType,
        from: { email: string; name: string },
        isTest = false
    ): Promise<void> {
        if (!this.sesV2Client) {
            throw new Error('SES is not configured - set SES_REGION and AWS credentials')
        }
        const distinctId = resolveEmailEngagementDistinctId(result.invocation)
        // Full signed code (with distinct_id + isTest) rides in the header; the short unsigned
        // carrier (no distinct_id/isTest) goes in the SES EmailTag, guaranteed under the 256-char
        // tag-value limit. The webhook reads the header first and only falls back to the tag.
        const trackingCode = this.trackingCodeSigner.generate({ ...result.invocation, distinctId }, isTest)
        const shortTrackingCode = this.trackingCodeSigner.generateShort(result.invocation)

        const htmlBody = params.html
            ? {
                  Html: {
                      Data: maybeAddPreheaderToEmail(
                          addTrackingToEmail(params.html, result.invocation, this.trackingCodeSigner, isTest),
                          params.preheader
                      ),
                      Charset: 'UTF-8',
                  },
              }
            : {}

        const sendEmailParams: SendEmailCommandInput = {
            FromEmailAddress: from.name ? `"${from.name}" <${from.email}>` : from.email,
            Destination: {
                ToAddresses: [params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email],
            },
            Content: {
                Simple: {
                    Subject: {
                        Data: sanitizeEmailSubject(params.subject),
                        Charset: 'UTF-8',
                    },
                    Body: {
                        Text: {
                            Data: params.text,
                            Charset: 'UTF-8',
                        },
                        ...htmlBody,
                    },
                },
            },
            ConfigurationSetName: 'posthog-messaging',
            // Short unsigned tag kept as a backwards-compat carrier for in-flight messages and
            // environments where the configuration set isn't yet emitting original headers.
            EmailTags: [{ Name: 'ph_id', Value: shortTrackingCode }],
            FeedbackForwardingEmailAddress: from.email,
        }

        // Authoritative tracking-code carrier: a custom MIME header. Header values aren't
        // 256-char-bounded the way SES tag values are, so they safely carry the signed code
        // (with distinct_id). The configuration set's event destination needs
        // `IncludeOriginalHeaders: true` for the webhook to surface this header.
        const trackingHeader: MessageHeader = { Name: TRACKING_CODE_HEADER_NAME, Value: trackingCode }

        const isTransactionalEmail = result.invocation.hogFunction?.metadata?.message_category_type === 'transactional'
        if (sendEmailParams.Content?.Simple) {
            const unsubscribeHeaders = !isTransactionalEmail
                ? this.generateUnsubscribeHeaders({
                      team_id: result.invocation.teamId,
                      identifier: params.to.email,
                  })
                : []
            sendEmailParams.Content.Simple.Headers = [...unsubscribeHeaders, trackingHeader]
        }

        const replyToAddresses = parseAddressList(params.replyTo)
        const ccAddresses = parseAddressList(params.cc)
        const bccAddresses = parseAddressList(params.bcc)

        if (replyToAddresses) {
            sendEmailParams.ReplyToAddresses = replyToAddresses
        }
        if (ccAddresses) {
            sendEmailParams.Destination!.CcAddresses = ccAddresses
        }
        if (bccAddresses) {
            sendEmailParams.Destination!.BccAddresses = bccAddresses
        }

        try {
            const response = await this.sesV2Client.send(new SendEmailCommand(sendEmailParams))
            if (!response.MessageId) {
                throw new Error('No messageId returned from SES')
            }
        } catch (error: unknown) {
            if (isSesThrottleError(error)) {
                sesThrottleResponsesTotal.inc({ error_code: error.name })
                throw new SESThrottleError(error.name, pickThrottleRetryDelayMs(), error.message)
            }
            const message = error instanceof Error ? error.message : String(error)
            throw new Error(`Failed to send email via SES: ${message}`)
        }
    }

    private generateUnsubscribeHeaders(
        recipient: Pick<RecipientManagerRecipient, 'team_id' | 'identifier'>
    ): MessageHeader[] {
        return [
            {
                Name: 'List-Unsubscribe',
                Value: `<${this.recipientTokensService.generateOneClickUnsubscribeUrl(recipient)}>`,
            },
            {
                Name: 'List-Unsubscribe-Post',
                Value: 'List-Unsubscribe=One-Click',
            },
        ]
    }
}
