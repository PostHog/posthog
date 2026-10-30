import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-webhook-callback',
    name: 'Webhook with callback',
    description:
        'Sends a webhook with a one-time callback URL, then waits until the receiver posts its reply to that URL.',
    icon_url: '/static/services/webhook.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let body := inputs.body ?? {}
if (typeof(body) != 'object') {
  throw Error('The JSON body must be an object, so the callback URL can be added to it')
}
body.callback_url := workflowCallbackUrl()

let payload := {
  'headers': inputs.headers,
  'body': body,
  'method': inputs.method
}

if (not empty(inputs.secret_headers)) {
  payload['secret_headers_input'] := 'secret_headers'
}

let res := fetch(inputs.url, payload)

if (res.status >= 400) {
  throw Error(f'Webhook failed with status {res.status}: {res.body}')
}

return {'await': {'max_wait': inputs.max_wait, 'label': 'callback'}}
`,
    inputs_schema: [
        {
            key: 'url',
            type: 'string',
            label: 'Webhook URL',
            secret: false,
            required: true,
            description: 'Endpoint URL to send the request to.',
        },
        {
            key: 'method',
            type: 'choice',
            label: 'Method',
            secret: false,
            choices: [
                { label: 'POST', value: 'POST' },
                { label: 'PUT', value: 'PUT' },
                { label: 'PATCH', value: 'PATCH' },
            ],
            default: 'POST',
            required: false,
            description: 'HTTP method to use for the request.',
        },
        {
            key: 'body',
            type: 'json',
            label: 'JSON Body',
            default: { event: '{event}', person: '{person}' },
            secret: false,
            required: false,
            description:
                'JSON object to send in the request body. The step adds a `callback_url` field. Post the reply to that URL as `{"result": {...}}`.',
        },
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
            default: { 'Content-Type': 'application/json' },
            description:
                'HTTP headers to send in the request. Put API tokens and other credentials in Secret headers instead.',
        },
        {
            key: 'secret_headers',
            type: 'dictionary',
            label: 'Secret headers',
            secret: true,
            required: false,
            templating: false,
            description:
                'HTTP headers that hold a credential, such as an API token. These are encrypted, hidden after saving, and kept out of the logs. Values are sent exactly as entered, without templating, and replace a plaintext header of the same name.',
        },
        {
            key: 'max_wait',
            type: 'choice',
            label: 'Wait for the reply for up to',
            secret: false,
            choices: [
                { label: '5 minutes', value: '5m' },
                { label: '1 hour', value: '1h' },
                { label: '6 hours', value: '6h' },
                { label: '24 hours', value: '24h' },
            ],
            default: '1h',
            required: true,
            description:
                'When no reply arrives in this time, the step fails. The callback URL stops working when the step stops waiting.',
        },
    ],
}
