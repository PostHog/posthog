import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'destination',
    id: 'template-hogflow-send-webhook',
    name: 'Native Webhook',
    description: "Send webhooks using PostHog's built-in webhook functionality",
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
let webhookConfig := inputs.webhook_config
let url := inputs.url
let method := inputs.method or 'POST'
let headers := inputs.headers or {}
let body := inputs.body

if (not url) {
    throw Error('Webhook URL is required')
}

let payload := {
    'method': method,
    'headers': headers
}

if (body and (method == 'POST' or method == 'PUT' or method == 'PATCH')) {
    payload.body := body
}

if (inputs.debug) {
    print('Sending webhook', url, payload)
}

// Use the webhook config from the integration if provided, otherwise direct fetch
let res
if (webhookConfig) {
    res := sendWebhook(webhookConfig, url, payload)
} else {
    res := fetch(url, payload)
}

if (res.status >= 400) {
    throw Error(f'Webhook failed with status {res.status}: {res.body}')
}

if (inputs.debug) {
    print('Webhook response', res.status, res.body)
}
`,
    inputs_schema: [
        {
            key: 'webhook_config',
            type: 'integration',
            integration: 'webhook',
            label: 'Webhook Configuration',
            secret: false,
            required: false,
            description: 'Optional webhook configuration for authentication and additional settings.',
        },
        {
            key: 'url',
            type: 'string',
            label: 'Webhook URL',
            secret: false,
            required: true,
            description: 'Target URL to send the webhook to.',
        },
        {
            key: 'method',
            type: 'choice',
            label: 'HTTP Method',
            secret: false,
            choices: [
                {
                    label: 'POST',
                    value: 'POST',
                },
                {
                    label: 'PUT',
                    value: 'PUT',
                },
                {
                    label: 'PATCH',
                    value: 'PATCH',
                },
                {
                    label: 'GET',
                    value: 'GET',
                },
                {
                    label: 'DELETE',
                    value: 'DELETE',
                },
            ],
            default: 'POST',
            required: false,
            description: 'HTTP method to use for the webhook request.',
        },
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
            default: { 'Content-Type': 'application/json' },
            description: 'HTTP headers to include in the webhook request.',
        },
        {
            key: 'body',
            type: 'json',
            label: 'Request Body',
            secret: false,
            required: false,
            default: {
                event: '{event}',
                person: '{person}',
                timestamp: '{event.timestamp}',
            },
            description: 'JSON payload to send in the webhook body (for POST/PUT/PATCH methods).',
        },
        {
            key: 'timeout',
            type: 'number',
            label: 'Timeout (seconds)',
            secret: false,
            required: false,
            default: 30,
            description: 'Request timeout in seconds.',
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the webhook responses for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
