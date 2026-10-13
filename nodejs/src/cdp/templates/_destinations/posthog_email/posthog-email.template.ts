import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'internal_destination',
    id: 'template-posthog-email',
    name: 'Email project members',
    description: 'Sends an alert email to members of this project',
    icon_url: '/static/posthog-icon.svg',
    category: ['Customer Success'],
    code_language: 'hog',
    code: `
let res := sendSystemEmail({
  'subject': inputs.subject,
  'body': inputs.body,
  'action_url': inputs.action_url,
  'action_label': inputs.action_label
})

if (not res.success) {
  throw Error(f'Email failed to send: {res.error}')
}
`.trim(),
    inputs_schema: [
        {
            key: 'subject',
            type: 'string',
            label: 'Subject',
            description: 'The subject line of the email.',
            secret: false,
            required: true,
        },
        {
            key: 'body',
            type: 'string',
            label: 'Body',
            description:
                'The message, as plain text. HTML is shown as text. Only the button link is added as a link, but some mail apps turn a web address in the text into a link.',
            secret: false,
            required: true,
        },
        {
            key: 'action_url',
            type: 'string',
            label: 'Button link',
            description: 'A link to a page in this project. The email shows it as a button.',
            secret: false,
            required: false,
        },
        {
            key: 'action_label',
            type: 'string',
            label: 'Button label',
            description: 'The text on the button.',
            default: 'Open in PostHog',
            secret: false,
            required: false,
        },
    ],
}
