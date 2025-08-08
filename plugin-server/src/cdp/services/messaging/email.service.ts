import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '~/cdp/types'
import { createAddLogFunction } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { CyclotronInvocationQueueParametersEmailType } from '~/schema/cyclotron'
import { isDevEnv } from '~/utils/env-utils'
import { fetch } from '~/utils/request'

import { Hub } from '../../../types'
import { generateMailjetCustomId } from './email-tracking.service'

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

    // Send email to local maildev instance for testing (DEBUG=1 only)
    private async executeSendEmailMaildev({
        params,
        addLog,
    }: {
        params: Omit<CyclotronInvocationQueueParametersEmailType, 'integrationId'>
        addLog: (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => void
    }) {
        const email = {
            to: params.to.email,
            toName: params.to.name,
            from: params.from.email,
            fromName: params.from.name,
            subject: params.subject,
            text: params.text,
            html: params.html,
        }

        const maildevHost = process.env.MAILDEV_HOST || 'localhost'
        const maildevPort = process.env.MAILDEV_PORT || '1025'
        const maildevWebPort = process.env.MAILDEV_WEB_PORT || '1080'
        const maildevWebUrl = `http://${maildevHost}:${maildevWebPort}`
        const maildevUrl = `http://${maildevHost}:${maildevPort}`

        const requiredFields = ['to', 'from', 'subject', 'text', 'html'] as const
        for (const field of requiredFields) {
            if (!(field in email) || !email[field]) {
                if (!email[field]) {
                    throw new Error(`Missing required email field: ${field}`)
                }
            }
        }

        const emailData = {
            from: email.fromName ? `"${email.fromName}" <${email.from}>` : email.from,
            to: email.toName ? `"${email.toName}" <${email.to}>` : email.to,
            subject: email.subject,
            text: email.text,
            html: email.html,
        }
        const maildevRequest = {
            url: `${maildevUrl}/email`,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json',
            },
            body: emailData,
        }

        const response = await fetch(maildevRequest.url, {
            method: maildevRequest.method,
            headers: maildevRequest.headers,
            body: JSON.stringify(maildevRequest.body),
        })

        if (response.status >= 400) {
            throw new Error(`Failed to send email to maildev with status ${response.status}`)
        }

        addLog('debug', `Email sent to your local maildev server: ${maildevWebUrl}`)
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

        const { integrationId, ...params } = invocation.queueParameters
        const integration = await this.hub.integrationManager.get(integrationId)

        let success: boolean = false

        try {
            if (!integration || integration.kind !== 'email' || integration.team_id !== invocation.teamId) {
                throw new Error('Email integration not found')
            }

            this.validateEmailDomain(integration, params.from.email)

            if (isDevEnv()) {
                await this.executeSendEmailMaildev({ params, addLog })
            }

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
                            CustomID: generateMailjetCustomId(invocation),
                        },
                    ],
                }),
            })

            // TODO: Add support for retries - in fact if it fails should we actually crash out the service?

            if (response.status >= 400) {
                throw new Error(`Failed to send email to ${params.to.email} with status ${response.status}`)
            } else {
                addLog('info', `Email sent to ${params.to.email}`)
            }

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
