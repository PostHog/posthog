// eslint-disable-next-line @typescript-eslint/no-unused-vars
import { AppMetrics } from '../../../worker/ingestion/app-metrics'
import { HogFunctionTemplate } from '../types'

// eslint-disable-next-line @typescript-eslint/no-unused-vars
interface MailjetEvent {
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

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'source_webhook',
    id: 'template-mailjet-webhook',
    name: 'Mailjet Webhook',
    description: 'Process Mailjet webhook events',
    icon_url: '/static/services/mailjet.png',
    category: ['Email Marketing'],
    hog: `
const event = request.body

if (!event || !event.event) {
    throw Error('Invalid webhook payload')
}

// Map Mailjet event types to our metric categories
const eventTypeToCategory = {
    'sent': 'email_sent',
    'open': 'email_opened',
    'click': 'email_clicked',
    'bounce': 'email_bounced',
    'blocked': 'email_blocked',
    'spam': 'email_spam',
    'unsub': 'email_unsubscribed'
}

const category = eventTypeToCategory[event.event] || 'email_other'

// Emit metrics for the event
appMetrics.queueMetric({
    teamId: project.id,
    pluginConfigId: -2, // -2 is hardcoded for webhooks
    category: category,
    successes: 1,
    properties: {
        event_type: event.event,
        email: event.email,
        campaign_id: event.mj_campaign_id,
        custom_campaign: event.customcampaign,
        message_id: event.message_id,
        error: event.error,
        error_type: event.error_related_to,
        smtp_reply: event.smtp_reply,
        blocked: event.blocked,
        timestamp: event.time
    }
})

return {
    statusCode: 200,
    body: { status: 'ok' }
}
`,
    inputs_schema: [
        {
            key: 'auth_token',
            type: 'string',
            label: 'Authentication Token',
            description: 'Token to validate incoming webhooks (optional)',
            secret: true,
            required: false,
        },
    ],
}
