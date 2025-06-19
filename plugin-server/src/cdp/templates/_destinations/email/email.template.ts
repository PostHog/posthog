import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-send-email',
    name: 'Send email',
    description: 'Sends an email',
    icon_url: '/static/posthog-icon.svg',
    category: ['Messaging'],
    hog: `sendEmail(inputs.email)`,
    inputs_schema: [
        {
            key: 'email',
            type: 'email',
            label: 'Email',
            description: 'The email to send',
            secret: false,
            required: true,
            default: false,
        },
    ],
}
