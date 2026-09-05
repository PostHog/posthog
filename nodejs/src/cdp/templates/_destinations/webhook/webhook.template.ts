import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'stable',
    type: 'destination',
    id: 'template-webhook',
    name: 'HTTP Webhook',
    description: 'Sends a webhook templated by the incoming event data',
    icon_url: '/static/services/webhook.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let payload := {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
}

if (not empty(inputs.signing_secret)) {
  payload['standard_webhooks'] := {
    'secret_input': 'signing_secret'
  }
}

// Names the input whose secret entries are headers, rather than the headers themselves: the
// fetch queue payload is stored as plaintext, so the executor resolves and merges them
// immediately before each attempt. inputs.headers here holds only the public entries.
payload['secret_headers_input'] := 'headers'

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
            description: 'Endpoint URL to send event data to.',
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
            description: 'HTTP method to use for the request.',
        },
        {
            key: 'body',
            type: 'json',
            label: 'JSON Body',
            default: { event: '{event}', person: '{person}' },
            secret: false,
            required: false,
            description: 'JSON payload to send in the request body.',
        },
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
            default: { 'Content-Type': 'application/json' },
            secret_entries: true,
            description:
                'HTTP headers to send in the request. Lock a header to store its value encrypted, for an API token or any other credential.',
        },
        {
            key: 'signing_secret',
            type: 'string',
            label: 'Signing secret',
            secret: true,
            required: false,
            description: 'Signs each request following the [Standard Webhooks](https://www.standardwebhooks.com) spec.',
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
