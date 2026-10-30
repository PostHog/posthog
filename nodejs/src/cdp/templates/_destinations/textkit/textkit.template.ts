import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'destination',
    id: 'template-textkit',
    name: 'TextKit SMS',
    description: 'Send an SMS with TextKit',
    icon_url: '/static/services/textkit.png',
    category: ['Communication'],
    code_language: 'hog',
    code: `
if (empty(inputs.api_key)) {
    throw Error('API key is required')
}

if (empty(inputs.to_number)) {
    throw Error('Recipient phone number is required')
}

if (empty(inputs.message)) {
    throw Error('Message is required')
}

let body := {
    'to': inputs.to_number,
    'body': inputs.message
}

if (not empty(inputs.from_number)) {
    body['from'] := inputs.from_number
}

if (inputs.debug) {
    print('Sending SMS', body)
}

// The key includes the recipient and the text because TextKit answers 409 when one key
// comes back with a different body, and one event can run several steps of a workflow.
let res := fetch('https://api.jointextkit.com/v1/messages', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json',
        'Idempotency-Key': sha256Hex(f'{event.uuid}:{inputs.to_number}:{inputs.message}')
    },
    'body': body
})

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to send SMS via TextKit: {res.status}: {res.body.error.message}')
}

if (inputs.debug) {
    print('SMS sent', res)
}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'API key',
            description: 'A TextKit API key (ssms_sk_...). Create one in the TextKit console.',
            secret: true,
            required: true,
        },
        {
            key: 'to_number',
            type: 'string',
            label: 'Recipient phone number',
            description: "The recipient's number in E.164 format, for example +14155550132.",
            default: '{person.properties.phone}',
            secret: false,
            required: true,
        },
        {
            key: 'message',
            type: 'string',
            label: 'Message',
            description: 'The message text, up to 1600 characters.',
            default: 'PostHog event {event.event} was triggered',
            secret: false,
            required: true,
        },
        {
            key: 'from_number',
            type: 'string',
            label: 'From number',
            description:
                'One of your TextKit numbers, or a sender pool ID (pool_...). You can leave this empty if your account has one number.',
            secret: false,
            required: false,
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the SMS requests and responses for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
