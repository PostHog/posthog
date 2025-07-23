import crypto from 'crypto'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '~/cdp/types'
import { createAddLogFunction } from '~/cdp/utils'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { ModifiedRequest } from '~/router'
import { fetch } from '~/utils/request'

import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'

export type MailjetEventType = keyof typeof EVENT_TYPE_TO_CATEGORY

export interface MailjetEvent {
    //Common fields
    event: MailjetEventType
    time: number
    email: string
    mj_campaign_id: number
    mj_contact_id: number
    customcampaign?: string
    message_id: string
    custom_id: string
    payload: any

    // `sent` event fields
    mj_message_id?: string
    smtp_reply?: string

    // `open` event fields
    ip?: string //also used for `unsub` event
    geo?: string //also used for `unsub` event
    agent?: string //also used for `unsub` event

    // `click` event fields
    url?: string

    // `bounce` event fields
    blocked?: boolean
    hard_bounce?: boolean
    error_related_to?: string // also used for `blocked` event
    error?: string // also used for `blocked` event
    comment?: string

    // `spam` event fields
    source?: string

    // `unsub` event fields
    mj_list_id?: string
}

export const EVENT_TYPE_TO_CATEGORY = {
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
                            URLTags: `ph_fn_id=${invocation.functionId}&ph_inv_id=${invocation.id}`,
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
    public async handleWebhook(req: ModifiedRequest): Promise<{ status: number; message?: string }> {
        const signature = req.headers['x-mailjet-signature'] as string
        const timestamp = req.headers['x-mailjet-timestamp'] as string

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
                logger.error('Invalid signature', { signature, timestamp, payload })
                return { status: 403, message: 'Invalid signature' }
            }

            // Track Mailjet webhook metrics
            // TODO: Zod validation
            const event = req.body as MailjetEvent
            const category = EVENT_TYPE_TO_CATEGORY[event.event]

            if (event) {
                mailjetWebhookEventsCounter.inc({ event_type: category })
                logger.info('Mailjet webhook event', { event, category })
            }

            return { status: 200, message: 'OK' }
        } catch (error) {
            mailjetWebhookErrorsCounter.inc({ error_type: error.name || 'unknown' })
            logger.error('Mailjet webhook error', { error })
            throw error
        }
    }
}
