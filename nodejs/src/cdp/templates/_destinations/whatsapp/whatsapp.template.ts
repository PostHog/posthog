import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-whatsapp',
    name: 'WhatsApp',
    description: 'Send WhatsApp messages using the WhatsApp Cloud API (Meta Graph API)',
    icon_url: '/static/services/whatsapp.png',
    category: ['Communication'],
    code_language: 'hog',
    code: `
let toNumber := inputs.to_number
let messageType := inputs.message_type
let phoneNumberId := inputs.phone_number_id
let accessToken := inputs.access_token
let apiVersion := empty(inputs.api_version) ? 'v21.0' : inputs.api_version

if (not toNumber) {
    throw Error('Recipient phone number is required')
}

if (not phoneNumberId) {
    throw Error('WhatsApp phone number ID is required')
}

if (not accessToken) {
    throw Error('WhatsApp access token is required')
}

let body := {
    'messaging_product': 'whatsapp',
    'recipient_type': 'individual',
    'to': toNumber
}

if (messageType == 'template') {
    if (empty(inputs.template_name)) {
        throw Error('Template name is required for template messages')
    }
    let templatePayload := {
        'name': inputs.template_name,
        'language': {
            'code': empty(inputs.template_language) ? 'en_US' : inputs.template_language
        }
    }
    body['type'] := 'template'
    body['template'] := templatePayload
} else {
    if (empty(inputs.message)) {
        throw Error('Message body is required for text messages')
    }
    body['type'] := 'text'
    body['text'] := {
        'preview_url': false,
        'body': inputs.message
    }
}

let url := f'https://graph.facebook.com/{apiVersion}/{phoneNumberId}/messages'

let payload := {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {accessToken}',
        'Content-Type': 'application/json'
    },
    'body': body
}

if (inputs.debug) {
    print('Sending WhatsApp message', url, payload)
}

let res := fetch(url, payload)

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to send WhatsApp message: {res.status} {res.body}')
}

if (inputs.debug) {
    print('WhatsApp message sent', res)
}
`,
    inputs_schema: [
        {
            key: 'access_token',
            type: 'string',
            label: 'Access token',
            description:
                'Your WhatsApp Cloud API access token from Meta. Generate it in the Meta for Developers app dashboard.',
            secret: true,
            required: true,
        },
        {
            key: 'phone_number_id',
            type: 'string',
            label: 'Phone number ID',
            description:
                'The phone number ID associated with your WhatsApp Business account (found in the WhatsApp Manager).',
            secret: false,
            required: true,
        },
        {
            key: 'api_version',
            type: 'string',
            label: 'Graph API version',
            description: 'The Meta Graph API version to call. Defaults to v21.0.',
            default: 'v21.0',
            secret: false,
            required: false,
        },
        {
            key: 'to_number',
            type: 'string',
            label: 'Recipient phone number',
            description: 'Phone number to send the message to (in E.164 format, e.g., +1234567890).',
            default: '{{ person.properties.phone }}',
            templating: 'liquid',
            secret: false,
            required: true,
        },
        {
            key: 'message_type',
            type: 'choice',
            label: 'Message type',
            description:
                'Text messages can only be sent within the 24-hour customer service window. Use a pre-approved template for business-initiated conversations.',
            choices: [
                { label: 'Text', value: 'text' },
                { label: 'Template', value: 'template' },
            ],
            default: 'text',
            secret: false,
            required: true,
        },
        {
            key: 'message',
            type: 'string',
            label: 'Message',
            description: 'Message body (max 4096 characters). Only used for text messages.',
            default: 'PostHog event {{ event.event }} was triggered',
            templating: 'liquid',
            secret: false,
            required: false,
        },
        {
            key: 'template_name',
            type: 'string',
            label: 'Template name',
            description: 'Name of the pre-approved WhatsApp message template. Only used for template messages.',
            secret: false,
            required: false,
        },
        {
            key: 'template_language',
            type: 'string',
            label: 'Template language',
            description: 'Language code for the template (e.g., en_US). Only used for template messages.',
            default: 'en_US',
            secret: false,
            required: false,
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the WhatsApp sending responses for debugging.',
            default: false,
            secret: false,
            required: false,
        },
    ],
}
