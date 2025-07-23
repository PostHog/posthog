import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-email',
    name: 'Send an email',
    description: 'Sends an email via PostHog',
    icon_url: '/static/hedgehog/mail-hog.png',
    category: ['Messaging'],
    code_language: 'hog',
    hog: `
let res := sendEmail(inputs.email);

if (not res.success) {
  throw Error(f'Email failed to send: {res.error}');
}
`,
    inputs_schema: [
        {
            key: 'email',
            type: 'native_email',
            label: 'Email',
            secret: false,
            required: true,
            description: 'The email to send.',
        },
    ],
}
