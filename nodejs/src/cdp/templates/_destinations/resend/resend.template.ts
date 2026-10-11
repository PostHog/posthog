import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'beta',
    type: 'destination',
    id: 'template-resend',
    name: 'Resend',
    description: 'Send an email with the Resend API',
    icon_url: '/static/services/resend.png',
    category: ['Email Marketing'],
    code_language: 'hog',
    code: `
let recipients := []
for (let address in splitByString(',', inputs.to)) {
    let trimmed := trim(address)
    if (notEmpty(trimmed)) {
        recipients := arrayPushBack(recipients, trimmed)
    }
}

if (empty(recipients)) {
    throw Error('Add at least one recipient email address.')
}

if (empty(inputs.text) and empty(inputs.html)) {
    throw Error('Add a plain text or HTML body.')
}

let body := {
    'from': inputs.from,
    'to': recipients,
    'subject': inputs.subject
}

if (notEmpty(inputs.text)) {
    body['text'] := inputs.text
}
if (notEmpty(inputs.html)) {
    body['html'] := inputs.html
}
if (notEmpty(inputs.reply_to)) {
    body['reply_to'] := inputs.reply_to
}

let res := fetch('https://api.resend.com/emails', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Resend rejected the email: {res.status}: {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'Resend API key',
            description: 'An API key with permission to send emails. It starts with re_.',
            secret: true,
            required: true,
        },
        {
            key: 'from',
            type: 'string',
            label: 'From',
            description:
                'The sender address. It must use a domain that you verified in Resend, for example "PostHog alerts <alerts@example.com>".',
            secret: false,
            required: true,
        },
        {
            key: 'to',
            type: 'string',
            label: 'To',
            description: 'One or more recipient email addresses, separated by commas. Resend accepts up to 50.',
            secret: false,
            required: true,
        },
        {
            key: 'subject',
            type: 'string',
            label: 'Subject',
            default: '{event.event}',
            secret: false,
            required: true,
        },
        {
            key: 'text',
            type: 'string',
            label: 'Plain text body',
            description: 'The plain text version of the email. Add this, an HTML body, or both.',
            default: '{event.event} by {person.name}\n\n{event.url}',
            secret: false,
            required: false,
        },
        {
            key: 'html',
            type: 'string',
            label: 'HTML body',
            description:
                'The HTML version of the email. Property values are not escaped, so do not use HTML with untrusted values.',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'reply_to',
            type: 'string',
            label: 'Reply to',
            default: '',
            secret: false,
            required: false,
        },
    ],
}
