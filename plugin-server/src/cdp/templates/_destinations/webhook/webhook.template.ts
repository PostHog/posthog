import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'beta',
    type: 'destination',
    id: 'template-webhook',
    name: 'HTTP Webhook',
    description: 'Sends a webhook templated by the incoming event data',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    hog: `
let payload := {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
}

if (inputs.debug) {
  print('Request', inputs.url, payload)
}

let res := fetch(inputs.url, payload);

if (res.status >= 400) {
  throw Error(f'Webhook failed with status {res.status}: {res.body}');
}

if (inputs.debug) {
  print('Response', res.status, res.body);
}
`,
    inputs_schema: [
        {
            key: 'url',
            type: 'string',
            label: 'Webhook URL',
            secret: false,
            required: true,
        },
        {
            key: 'method',
            type: 'choice',
            label: 'Method',
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
        },
        {
            key: 'body',
            type: 'json',
            label: 'JSON Body',
            default: { event: '{event}', person: '{person}' },
            secret: false,
            required: false,
        },
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
            default: { 'Content-Type': 'application/json' },
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the response of http calls for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
