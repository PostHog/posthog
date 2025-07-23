import crypto from 'crypto'
import { Counter } from 'prom-client'

import {
    AppMetricType,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    IntegrationType,
    MinimalAppMetric,
} from '~/cdp/types'
import { createAddLogFunction } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { ModifiedRequest } from '~/router'
import { fetch } from '~/utils/request'

import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'
import { MailjetEventType, MailjetWebhookEvent } from './types'

export const EVENT_TYPE_TO_CATEGORY: Record<MailjetEventType, string> = {
    sent: 'email_sent',
    open: 'email_opened',
    click: 'email_clicked',
    bounce: 'email_bounced',
    blocked: 'email_blocked',
    spam: 'email_spam',
    unsub: 'email_unsubscribed',
} as const

export const mailjetWebhookEventsCounter = new Counter({
    name: 'mailjet_webhook_events_total',
    help: 'Total number of Mailjet webhook events received',
    labelNames: ['event_type'],
})

export const mailjetWebhookErrorsCounter = new Counter({
    name: 'mailjet_webhook_errors_total',
    help: 'Total number of Mailjet webhook processing errors',
    labelNames: ['error_type'],
})

export type MailjetEmailRequest = {
    from: {
        email: string
        name: string
    }
    to: {
        email: string
        name: string
    }[]
    subject: string
    text: string
    html: string
}

const parseCustomId = (customId: string): { functionId: string; invocationId: string } | null => {
    // customId  is like ph_fn_id=function-1&ph_inv_id=invocation-1
    try {
        const params = new URLSearchParams(customId)
        const functionId = params.get('ph_fn_id')
        const invocationId = params.get('ph_inv_id')
        if (!functionId || !invocationId) {
            return null
        }
        return { functionId, invocationId }
    } catch (error) {
        return null
    }
}

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
                            CustomID: `ph_fn_id=${invocation.functionId}&ph_inv_id=${invocation.id}`,
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
            metric_kind: success ? 'success' : 'failure',
            metric_name: success ? 'email_sent' : 'email_failed',
            count: 1,
        })

        return result
    }

    // eslint-disable-next-line @typescript-eslint/require-await
    public async handleWebhook(
        req: ModifiedRequest
    ): Promise<{ status: number; message?: string; metrics?: AppMetricType[] }> {
        const signature = req.headers['x-mailjet-signature'] as string
        const timestamp = req.headers['x-mailjet-timestamp'] as string

        const okResponse = { status: 200, message: 'OK' }

        if (!signature || !timestamp || !req.rawBody) {
            return { status: 403, message: 'Missing required headers or body' }
        }

        const payload = `${timestamp}.${req.rawBody.toString()}`
        const hmac = crypto.createHmac('sha256', this.hub.MAILJET_SECRET_KEY).update(payload).digest()

        try {
            const signatureBuffer = Buffer.from(signature, 'hex')
            if (
                hmac.length !== signatureBuffer.length ||
                !crypto.timingSafeEqual(new Uint8Array(hmac), new Uint8Array(signatureBuffer))
            ) {
                mailjetWebhookErrorsCounter.inc({ error_type: 'invalid_signature' })
                logger.error('[EmailService] handleWebhook: Invalid signature', {
                    signature,
                    timestamp,
                    payload,
                })
                return { status: 403, message: 'Invalid signature' }
            }

            const event = req.body as MailjetWebhookEvent
            const category = EVENT_TYPE_TO_CATEGORY[event.event]
            const { functionId, invocationId } = parseCustomId(event.CustomID || '') || {}

            if (!functionId || !invocationId) {
                mailjetWebhookErrorsCounter.inc({ error_type: 'invalid_custom_id' })
                logger.error('[EmailService] handleWebhook: Invalid custom ID', { event })
                return okResponse
            }

            if (!category) {
                mailjetWebhookErrorsCounter.inc({ error_type: 'unmapped_event_type' })
                logger.error('[EmailService] handleWebhook: Unmapped event type', { event })
                return okResponse
            }

            mailjetWebhookEventsCounter.inc({ event_type: category })
            logger.debug('[EmailService] handleWebhook: Mailjet webhook event', { event, category })

            // TODO: Move this function to a dedicated email webhook service - makes more sense...
            // NOTE: Here we need to try and load the fn or flow for the ID to track the metric for it...
        } catch (error) {
            mailjetWebhookErrorsCounter.inc({ error_type: error.name || 'unknown' })
            logger.error('[EmailService] handleWebhook: Mailjet webhook error', { error })
            throw error
        }
    }
}
