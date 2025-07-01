import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-hogflow-send-sms-twilio',
    name: 'Twilio SMS',
    description: 'Send SMS messages using Twilio',
    icon_url: '/static/services/twilio.png',
    category: ['Communication'],
    hog: `
let twilioConfig := inputs.twilio_config
let toNumber := inputs.to_number
let message := inputs.message
let fromNumber := inputs.from_number

if (not toNumber) {
    throw Error('Recipient phone number is required')
}

if (not message) {
    throw Error('SMS message is required')
}

if (not fromNumber) {
    throw Error('From phone number is required')
}

let payload := {
    'To': toNumber,
    'Body': message,
    'From': fromNumber
}

if (inputs.debug) {
    print('Sending SMS', payload)
}

// Use the Twilio config from the integration
let res := sendTwilioSMS(twilioConfig, payload)

if (inputs.debug) {
    print('SMS sent', res)
}
`,
    inputs_schema: [
        {
            key: 'twilio_config',
            type: 'integration',
            integration: 'twilio',
            label: 'Twilio Configuration',
            secret: false,
            required: true,
            description: 'Twilio account configuration for sending SMS messages.',
        },
        {
            key: 'to_number',
            type: 'string',
            label: 'Recipient Phone Number',
            secret: false,
            required: true,
            description: 'Phone number to send the SMS to (in E.164 format, e.g., +1234567890).',
            default: '{person.properties.phone}',
        },
        {
            key: 'from_number',
            type: 'string',
            label: 'From Phone Number',
            secret: false,
            required: true,
            description: 'Twilio phone number to send from (in E.164 format, e.g., +1234567890).',
        },
        {
            key: 'message',
            type: 'string',
            label: 'SMS Message',
            secret: false,
            required: true,
            description: 'SMS message content (max 1600 characters).',
            default: 'PostHog event {event.event} was triggered',
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
