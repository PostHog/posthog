import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-email',
    name: 'Email',
    description: 'Sends an email via PostHog email service',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code: `
    let res := sendEmail(inputs.email)

    if (not res.success) {
        throw Error(f'Email failed to send: {res.error}')
    }
    `,
    code_language: 'hog',

    inputs_schema: [
        {
            type: 'native_email',
            key: 'email',
            label: 'Email message',
            integration: 'email',
            required: true,
            default: {
                to: {
                    email: '{person.properties.email}',
                },
                from: null,
                subject: 'PostHog Notification',
                text: '',
                html: '',
            },
            secret: false,
            description: 'The email message to send. Configure the recipient, sender, subject, and content.',
        },
    ],
}
