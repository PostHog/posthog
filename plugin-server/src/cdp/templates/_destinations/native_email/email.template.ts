import { NativeTemplate } from '~/cdp/types'

interface EmailPayload {
    email: {
        to: string
        toName?: string
        from: string
        fromName?: string
        subject: string
        text?: string
        html?: string
    }
}

interface MaildevEmailRequest {
    url: string
    method: 'POST'
    headers: Record<string, string>
    body: any
}

function getMaildevEmailDeliveryRequest(payload: EmailPayload): MaildevEmailRequest {
    const { email } = payload

    const requiredFields = ['to', 'from', 'subject', 'text', 'html'] as const
    for (const field of requiredFields) {
        if (!email[field]) {
            throw new Error(`Missing required email field: ${field}`)
        }
    }

    const maildevHost = process.env.MAILDEV_HOST || 'localhost'
    const maildevPort = process.env.MAILDEV_PORT || '1025'
    const maildevUrl = `http://${maildevHost}:${maildevPort}`

    const emailData = {
        from: email.fromName ? `"${email.fromName}" <${email.from}>` : email.from,
        to: email.toName ? `"${email.toName}" <${email.to}>` : email.to,
        subject: email.subject,
        text: email.text || '',
        html: email.html || email.text || '',
    }

    return {
        url: `${maildevUrl}/email`,
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
        },
        body: emailData,
    }
}

export const template: NativeTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'native-email',
    name: 'Native email',
    description: 'Sends a native email via SMTP server (e.g., maildev)',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    perform: (request, { payload }) => {
        // TODO: Send mail via SES / Mailjet in addition to maildev
        if (['test', 'dev'].includes(process.env.NODE_ENV || '')) {
            // On dev, send all emails to maildev for testing
            const emailRequest = getMaildevEmailDeliveryRequest(payload)

            try {
                return request(emailRequest.url, {
                    method: emailRequest.method,
                    headers: emailRequest.headers,
                    json: emailRequest.body,
                })
            } catch (error) {
                throw new Error(`Failed to send email to maildev: ${error.message}`)
            }
        }
    },
    inputs_schema: [
        {
            type: 'native-email',
            key: 'email',
            label: 'Email message',
            integration: 'email',
            required: true,
            default: {
                to: '{person.properties.email}',
                from: null,
                subject: 'PostHog Notification',
                text: 'Hello from PostHog!',
                html: '<h1>Hello from PostHog!</h1>',
            },
            secret: false,
            description: 'The email message to send. Configure the recipient, sender, subject, and content.',
        },
    ],
}
