import crypto from 'crypto'
import express from 'express'
import { Counter } from 'prom-client'

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

export class MessagingMailjetManagerService {
    constructor(private hub: Hub) {}

    // eslint-disable-next-line @typescript-eslint/require-await
    public async handleWebhook(
        req: express.Request & { rawBody?: Buffer }
    ): Promise<{ status: number; message?: string }> {
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
