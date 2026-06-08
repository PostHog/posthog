import { MessageHeader, SESv2Client, SendEmailCommand, SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { DateTime } from 'luxon'
import { SendMailOptions } from 'nodemailer'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '~/cdp/types'
import { createAddLogFunction, logEntry } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'

import { IntegrationManagerService } from '../managers/integration-manager.service'
import { RecipientManagerRecipient } from '../managers/recipients-manager.service'
import { addTrackingToEmail } from './email-tracking.service'
import { mailDevTransport, mailDevWebUrl } from './helpers/maildev'
import { maybeAddPreheaderToEmail } from './helpers/preheader'
import { generateEmailTrackingCode } from './helpers/tracking-code'
import { RecipientTokensService } from './recipient-tokens.service'

// SES throttle error names we treat as retryable. SDK v3 throws these as named
// exception classes; we match by `.name` so we don't need a typed import for
// every error class. SendingPausedException / AccountSuspendedException are
// intentionally excluded — those signal a sustained problem with the sender,
// not a transient TPS overshoot, so they must surface as terminal failures.
const SES_THROTTLE_ERROR_NAMES = new Set(['TooManyRequestsException', 'ThrottlingException'])

// Cap on app-layer retries _on top of_ the SDK's built-in retries. SES SDK v3
// already retries 3 times with adaptive backoff; we add a second tier so a
// genuine multi-second backlog can still drain without dropping mail.
const SES_THROTTLE_MAX_ATTEMPTS = 5
const SES_THROTTLE_BASE_DELAY_MS = 1_000
const SES_THROTTLE_MAX_DELAY_MS = 60_000
const SES_THROTTLE_JITTER_MS = 500

const sesThrottleRetriesCounter = new Counter({
    name: 'cdp_email_ses_throttle_retries_total',
    help: 'Email sends rescheduled because SES returned a throttling exception',
    labelNames: ['outcome'],
})

export function isSesThrottleError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const e = error as { name?: string; $metadata?: { httpStatusCode?: number } }
    if (e.name && SES_THROTTLE_ERROR_NAMES.has(e.name)) {
        return true
    }
    return e.$metadata?.httpStatusCode === 429
}

export function computeSesThrottleBackoffMs(previousAttempts: number): number {
    const exp = Math.min(SES_THROTTLE_BASE_DELAY_MS * 2 ** previousAttempts, SES_THROTTLE_MAX_DELAY_MS)
    return exp + Math.floor(Math.random() * SES_THROTTLE_JITTER_MS)
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
        encryptionSaltKeys: string,
        siteUrl: string
    ) {
        this.sesV2Client = this.sesConfig.sesRegion
            ? new SESv2Client({
                  region: this.sesConfig.sesRegion,
                  endpoint: this.sesConfig.sesEndpoint || undefined,
              })
            : null
        this.recipientTokensService = new RecipientTokensService(encryptionSaltKeys, siteUrl)
    }

    // Send email
    public async executeSendEmail(
        invocation: CyclotronJobInvocationHogFunction
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

        try {
            if (!integration || integration.kind !== 'email' || integration.team_id !== invocation.teamId) {
                throw new Error('Email integration not found')
            }

            const from = this.resolveFromSender(integration)

            switch (integration.config.provider ?? 'ses') {
                case 'maildev':
                    await this.sendEmailWithMaildev(result, params, from)
                    break
                case 'ses':
                    await this.sendEmailWithSES(result, params, from)
                    break

                case 'unsupported':
                    throw new Error('Email delivery mode not supported')
            }

            addLog('info', `Email sent to ${params.to.email}`)
            success = true
        } catch (error) {
            if (isSesThrottleError(error)) {
                const previousAttempts = Number(
                    (invocation.queueMetadata as { sesThrottleAttempts?: number } | undefined)?.sesThrottleAttempts ?? 0
                )
                if (previousAttempts < SES_THROTTLE_MAX_ATTEMPTS) {
                    const backoffMs = computeSesThrottleBackoffMs(previousAttempts)
                    const nextAttempt = previousAttempts + 1
                    addLog(
                        'warn',
                        `SES rate-limited; rescheduling email in ${backoffMs}ms (attempt ${nextAttempt}/${SES_THROTTLE_MAX_ATTEMPTS})`
                    )
                    // Preserve queueParameters so the next dequeue knows what to send;
                    // createInvocationResult clears them by default.
                    result.finished = false
                    result.error = undefined
                    result.invocation.queue = 'email'
                    result.invocation.queueParameters = invocation.queueParameters
                    result.invocation.queueScheduledAt = DateTime.now().plus({ milliseconds: backoffMs })
                    result.invocation.queueMetadata = {
                        ...(invocation.queueMetadata ?? {}),
                        sesThrottleAttempts: nextAttempt,
                    }
                    result.metrics.push({
                        team_id: invocation.teamId,
                        app_source_id: invocation.parentRunId ?? invocation.functionId,
                        instance_id: invocation.state.actionId || invocation.id,
                        metric_kind: 'email',
                        metric_name: 'email_rate_limited',
                        count: 1,
                    })
                    sesThrottleRetriesCounter.inc({ outcome: 'rescheduled' })
                    // Skip the vmState push + email_failed metric — we're not done yet.
                    return result
                }
                sesThrottleRetriesCounter.inc({ outcome: 'exhausted' })
                addLog(
                    'error',
                    `SES rate-limited; giving up after ${SES_THROTTLE_MAX_ATTEMPTS} retry attempts: ${error.message}`
                )
            } else {
                addLog('error', error.message)
            }
            result.error = error.message
            result.finished = true
        }

        // Push the response to the VM stack if running inline (not from the email queue)
        result.invocation.state.vmState?.stack.push({
            success,
        })

        result.metrics.push({
            team_id: invocation.teamId,
            app_source_id: invocation.parentRunId ?? invocation.functionId,
            instance_id: invocation.state.actionId || invocation.id,
            metric_kind: 'email',
            metric_name: success ? 'email_sent' : 'email_failed',
            count: 1,
        })

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
        from: { email: string; name: string }
    ): Promise<void> {
        // This can timeout but there is no native timeout so we do our own one
        const mailOptions: SendMailOptions = {
            from: from.name ? `"${from.name}" <${from.email}>` : from.email,
            to: params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email,
            subject: sanitizeEmailSubject(params.subject),
            text: params.text,
            ...(params.html ? { html: addTrackingToEmail(params.html, result.invocation) } : {}),
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
        from: { email: string; name: string }
    ): Promise<void> {
        if (!this.sesV2Client) {
            throw new Error('SES is not configured - set SES_REGION and AWS credentials')
        }
        const trackingCode = generateEmailTrackingCode(result.invocation)

        const htmlBody = params.html
            ? {
                  Html: {
                      Data: maybeAddPreheaderToEmail(
                          addTrackingToEmail(params.html, result.invocation),
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
            EmailTags: [{ Name: 'ph_id', Value: trackingCode }],
            FeedbackForwardingEmailAddress: from.email,
        }

        const isTransactionalEmail = result.invocation.hogFunction?.metadata?.message_category_type === 'transactional'
        // Automatically add unsubscribe headers for non-transactional emails
        if (sendEmailParams.Content?.Simple && !isTransactionalEmail) {
            sendEmailParams.Content.Simple.Headers = this.generateUnsubscribeHeaders({
                team_id: result.invocation.teamId,
                identifier: params.to.email,
            })
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
            // Re-throw throttle errors unwrapped so executeSendEmail can detect
            // them by name / $metadata.httpStatusCode and reschedule the invocation.
            if (isSesThrottleError(error)) {
                throw error
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
