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
            key: 'email_provider',
            type: 'integration',
            integration: 'email',
            label: 'Email configuration',
            secret: false,
            required: true,
            description: 'Email service configuration for sending emails.',
        },
        {
            key: 'template',
            type: 'email',
            label: 'Email template',
            default: {
                to: '{person.properties.email}',
            },
            secret: false,
            required: true,
        },
    ],
}
