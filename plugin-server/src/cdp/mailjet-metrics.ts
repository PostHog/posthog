import { Counter } from 'prom-client'

export interface MailjetEvent {
    //Common fields
    event: string
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
    mj_list_id: string
}

export const eventTypeToCategory = {
    sent: 'email_sent',
    open: 'email_opened',
    click: 'email_clicked',
    bounce: 'email_bounced',
    blocked: 'email_blocked',
    spam: 'email_spam',
    unsub: 'email_unsubscribed',
}

export const mailjetWebhookEvents = new Counter({
    name: 'mailjet_webhook_events_total',
    help: 'Total number of Mailjet webhook events received',
    labelNames: ['event_type'],
})

export const mailjetWebhookErrors = new Counter({
    name: 'mailjet_webhook_errors_total',
    help: 'Total number of Mailjet webhook processing errors',
    labelNames: ['error_type'],
})
