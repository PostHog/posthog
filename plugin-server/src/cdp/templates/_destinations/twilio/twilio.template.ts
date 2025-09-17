import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-twilio',
    name: 'Twilio SMS',
    description: 'Send SMS messages using Twilio',
    icon_url: '/static/services/twilio.png',
    category: ['Communication'],
    code_language: 'hog',
    code: `
let toNumber := inputs.to_number
let message := inputs.message
let fromNumber := inputs.from_number

if (not toNumber) {
    throw Error('Recipient phone number is required')
}

if (not message) {
    throw Error('SMS message is required')
}

let encodedTo := encodeURLComponent(toNumber)
let encodedFrom := encodeURLComponent(fromNumber)
let encodedSmsBody := encodeURLComponent(message)
let base64EncodedAuth := base64Encode(f'{inputs.twilio_account.account_sid}:{inputs.twilio_account.auth_token}')

let url := f'https://api.twilio.com/2010-04-01/Accounts/{inputs.twilio_account.account_sid}/Messages.json'
let body := f'To={encodedTo}&From={encodedFrom}&Body={encodedSmsBody}'

let payload := {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64EncodedAuth}',
        'Content-Type': 'application/x-www-form-urlencoded'
    },
    'body': body
}

if (inputs.debug) {
    print('Sending SMS', url, payload)
}

// Use the Twilio config from the integration
let res := fetch(url, payload)

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to send SMS via Twilio: {res.status} {res.body}')
}

if (inputs.debug) {
    print('SMS sent', res)
}
`,
    inputs_schema: [
        {
            key: 'twilio_account',
            type: 'integration',
            integration: 'twilio',
            label: 'Twilio account',
            requiredScopes: 'placeholder',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'from_number',
            type: 'integration_field',
            integration_key: 'twilio_account',
            integration_field: 'twilio_phone_number',
            label: 'From Phone Number',
            description: 'Your Twilio phone number',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'to_number',
            type: 'string',
            label: 'Recipient phone number',
            secret: false,
            required: true,
            description: 'Phone number to send the SMS to (in E.164 format, e.g., +1234567890).',
            default: '{{ person.properties.phone }}',
            templating: 'liquid',
        },
        {
            key: 'message',
            type: 'string',
            label: 'Message',
            secret: false,
            required: true,
            description: 'SMS message content (max 1600 characters).',
            default: 'PostHog event {{ event.event }} was triggered',
            templating: 'liquid',
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the SMS sending responses for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
