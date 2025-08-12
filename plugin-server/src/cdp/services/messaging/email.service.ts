import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '~/cdp/types'
import { createAddLogFunction, logEntry } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'
import { isDevEnv } from '~/utils/env-utils'
import { fetch } from '~/utils/request'

import { Hub } from '../../../types'
import { generateMailjetCustomId } from './email-tracking.service'
import { mailDevTransport, mailDevWebUrl } from './helpers/maildev'

export class EmailService {
    constructor(private hub: Hub) {}

    private validateEmailDomain(integration: IntegrationType, email: string): void {
        // First check its a valid domain in general
        const domain = email.split('@')[1]
        // Then check its the same as the integration domain
        if (!domain || (integration.config.domain && integration.config.domain !== domain)) {
            throw new Error(
                `The selected email integration domain (${integration.config.domain}) does not match the 'from' email domain (${domain})`
            )
        }

        if (!integration.config.mailjet_verified) {
            throw new Error('The selected email integration domain is not verified')
        }
    }

    private getEmailDeliveryMode(): 'mailjet' | 'maildev' | 'unsupported' {
        if (this.hub.MAILJET_PUBLIC_KEY && this.hub.MAILJET_SECRET_KEY) {
            return 'mailjet'
        }

        if (isDevEnv() && mailDevTransport) {
            return 'maildev'
        }
        return 'unsupported'
    }

    private async sendEmailWithMailjet(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType
    ): Promise<void> {
        // First we need to lookup the email sending domain of the given team
        const response = await fetch('https://api.mailjet.com/v3.1/send', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Basic ${Buffer.from(
                    `${this.hub.MAILJET_PUBLIC_KEY}:${this.hub.MAILJET_SECRET_KEY}`
                ).toString('base64')}`,
            },
            body: JSON.stringify({
                Messages: [
                    {
                        From: {
                            Email: params.from.email,
                            Name: params.from.name,
                        },
                        To: [
                            {
                                Email: params.to.email,
                                Name: params.to.name,
                            },
                        ],
                        Subject: params.subject,
                        TextPart: params.text,
                        HTMLPart: params.html,
                        CustomID: generateMailjetCustomId(result.invocation),
                    },
                ],
            }),
        })

        // TODO: Add support for retries - in fact if it fails should we actually crash out the service?
        if (response.status >= 400) {
            throw new Error(`Failed to send email to ${params.to.email} with status ${response.status}`)
        }
    }

    // Send email to local maildev instance for testing (DEBUG=1 only)
    private async sendEmailWithMaildev(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersEmailType
    ): Promise<void> {
        const response = await mailDevTransport!.sendMail({
            from: params.from.name ? `"${params.from.name}" <${params.from.email}>` : params.from.email,
            to: params.to.name ? `"${params.to.name}" <${params.to.email}>` : params.to.email,
            subject: params.subject,
            text: params.text,
            html: params.html,
        })

        if (!response.accepted) {
            throw new Error(`Failed to send email to maildev: ${JSON.stringify(response)}`)
        }

        result.logs.push(logEntry('debug', `Email sent to your local maildev server: ${mailDevWebUrl}`))
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

            this.validateEmailDomain(integration, params.from.email)

            switch (this.getEmailDeliveryMode()) {
                case 'maildev':
                    await this.sendEmailWithMaildev(result, params)
                    break
                case 'mailjet':
                    await this.sendEmailWithMailjet(result, params)
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
            success: !!success,
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
}
