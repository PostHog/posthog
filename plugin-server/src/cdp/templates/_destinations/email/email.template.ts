import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-email',
    name: 'Send an email',
    description: "Send an email using PostHog's built-in email service",
    icon_url: '/static/hedgehog/mail-hog.png',
    category: ['Communication'],
    hog: `
let emailConfig := inputs.email_config
let recipient := inputs.recipient
let subject := inputs.subject
let body := inputs.body

if (not recipient) {
    throw Error('Recipient email is required')
}

if (not subject) {
    throw Error('Email subject is required')
}

if (not body) {
    throw Error('Email body is required')
}

let payload := {
    'to': recipient,
    'subject': subject,
    'body': body,
    'html': inputs.html_body or false
}

if (inputs.debug) {
    print('Sending email', payload)
}

// Use the email config from the integration
let res := sendEmail(emailConfig, payload)

if (inputs.debug) {
    print('Email sent', res)
}
`,
    inputs_schema: [
        {
            key: 'email_config',
            type: 'integration',
            integration: 'email',
            label: 'Email Configuration',
            secret: false,
            required: true,
            description: 'Email service configuration for sending emails.',
        },
        {
            key: 'recipient',
            type: 'string',
            label: 'Recipient Email',
            secret: false,
            required: true,
            description: 'Email address to send the message to.',
            default: '{person.properties.email}',
        },
        {
            key: 'subject',
            type: 'string',
            label: 'Subject',
            secret: false,
            required: true,
            description: 'Email subject line.',
            default: 'PostHog Event Notification',
        },
        {
            key: 'body',
            type: 'string',
            label: 'Email Body',
            secret: false,
            required: true,
            description: 'Email message content.',
            default: 'Event {event.event} was triggered by {person.properties.email or "Unknown"}',
        },
        {
            key: 'html_body',
            type: 'boolean',
            label: 'HTML Body',
            secret: false,
            required: false,
            default: false,
            description: 'Whether the email body contains HTML content.',
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the email sending responses for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
