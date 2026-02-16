import { MessageHeader, SESv2Client, SendEmailCommand, SendEmailCommandInput } from '@aws-sdk/client-sesv2'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '~/cdp/types'
import { createAddLogFunction, logEntry } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'

import { Hub } from '../../../types'
import { RecipientManagerRecipient } from '../managers/recipients-manager.service'
import { addTrackingToEmail } from './email-tracking.service'
import { mailDevTransport, mailDevWebUrl } from './helpers/maildev'
import { maybeAddPreheaderToEmail } from './helpers/preheader'
import { generateEmailTrackingCode } from './helpers/tracking-code'
import { RecipientTokensService } from './recipient-tokens.service'

export type EmailServiceHub = Pick<
    Hub,
    | 'SES_ACCESS_KEY_ID'
    | 'SES_SECRET_ACCESS_KEY'
    | 'SES_REGION'
    | 'SES_ENDPOINT'
    | 'SITE_URL'
    | 'ENCRYPTION_SALT_KEYS'
    | 'integrationManager'
>

export class EmailService {
    sesV2Client: SESv2Client

    private recipientTokensService: RecipientTokensService

    constructor(private hub: EmailServiceHub) {
        this.sesV2Client = new SESv2Client({
            region: this.hub.SES_REGION,
            endpoint: this.hub.SES_ENDPOINT || undefined,
        })
        this.recipientTokensService = new RecipientTokensService(hub)
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
        const integration = await this.hub.integrationManager.get(params.from.integrationId)

        let success: boolean = false

        try {
            if (!integration || integration.kind !== 'email' || integration.team_id !== invocation.teamId) {
                throw new Error('Email integration not found')
            }

            this.validateEmailDomain(integration, params)

            switch (integration.config.provider ?? 'ses') {
                case 'maildev':
                    await this.sendEmailWithMaildev(result, params)
                    break
                case 'ses':
                    await this.sendEmailWithSES(result, params)
                    break

                case 'unsupported':
                    throw new Error('Email delivery mode not supported')
            }

            addLog('info', `Email sent to ${params.to.email}`)
            success = true
        } catch (error) {
            addLog('error', error.message)
            result.error = error.message
            result.finished = true
        }

        // Finally we create the response object as the VM expects
        result.invocation.state.vmState!.stack.push({
            success,
        })

        result.metrics.push({
            team_id: invocation.teamId,
            app_source_id: invocation.functionId,
            instance_id: invocation.id,
            metric_kind: 'email',
            metric_name: success ? 'email_sent' : 'email_failed',
            count: 1,
        })

        return result
    }

    private validateEmailDomain(
        integration: IntegrationType,
        params: CyclotronInvocationQueueParametersEmailType
    ): void {
        // Currently we enforce using the name and email set on the integration

        if (!integration.config.verified) {
            throw new Error('The selected email integration domain is not verified')
        }

        if (!integration.config.email || !integration.config.name) {
            throw new Error('The selected email integration is not configured correctly')
        }

        params.from.email = integration.config.email
        params.from.name = integration.config.name
    }

    // Send email to local maildev instance for testing (DEBUG=1 only)
    private async sendEmailWithMaildev(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType
    ): Promise<void> {
        // This can timeout but there is no native timeout so we do our own one
        const response = await mailDevTransport!.sendMail({
            from: params.from.name ? `"${params.from.name}" <${params.from.email}>` : params.from.email,
            to: params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email,
            subject: params.subject,
            text: params.text,
            html: addTrackingToEmail(params.html, result.invocation),
        })

        if (!response.accepted) {
            throw new Error(`Failed to send email to maildev: ${JSON.stringify(response)}`)
        }

        result.logs.push(logEntry('debug', `Email sent to your local maildev server: ${mailDevWebUrl}`))
    }

    private async sendEmailWithSES(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType
    ): Promise<void> {
        if (!this.sesV2Client) {
            throw new Error('SES is not configured - set SES_REGION and AWS credentials')
        }
        const trackingCode = generateEmailTrackingCode(result.invocation)
        const htmlWithTracking = addTrackingToEmail(params.html, result.invocation)
        const htmlWithTrackingAndPreheader = maybeAddPreheaderToEmail(htmlWithTracking, params.preheader)

        const sendEmailParams: SendEmailCommandInput = {
            FromEmailAddress: params.from.name ? `"${params.from.name}" <${params.from.email}>` : params.from.email,
            Destination: {
                ToAddresses: [params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email],
            },
            Content: {
                Simple: {
                    Subject: {
                        Data: params.subject,
                        Charset: 'UTF-8',
                    },
                    Body: {
                        Html: {
                            Data: htmlWithTrackingAndPreheader,
                            Charset: 'UTF-8',
                        },
                        Text: {
                            Data: params.text,
                            Charset: 'UTF-8',
                        },
                    },
                },
            },
            ConfigurationSetName: 'posthog-messaging',
            EmailTags: [{ Name: 'ph_id', Value: trackingCode }],
            FeedbackForwardingEmailAddress: params.from.email,
        }

        const isTransactionalEmail = result.invocation.hogFunction.metadata?.message_category_type === 'transactional'
        // Automatically add unsubscribe headers for non-transactional emails
        if (sendEmailParams.Content?.Simple && !isTransactionalEmail) {
            sendEmailParams.Content.Simple.Headers = this.generateUnsubscribeHeaders({
                team_id: result.invocation.teamId,
                identifier: params.to.email,
            })
        }

        if (params.replyTo && params.replyTo.trim()) {
            sendEmailParams.ReplyToAddresses = params.replyTo
                .split(',')
                .map((addr) => addr.trim())
                .filter((addr) => addr.length > 0)
        }

        try {
            const response = await this.sesV2Client.send(new SendEmailCommand(sendEmailParams))
            if (!response.MessageId) {
                throw new Error('No messageId returned from SES')
            }
        } catch (error: unknown) {
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
