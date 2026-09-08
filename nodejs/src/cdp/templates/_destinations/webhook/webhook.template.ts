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

if (inputs.debug) {
  print('Request', inputs.url, payload)
}

// The secret headers are merged after the debug log so that they stay out of the run logs.
if (not empty(inputs.secret_headers)) {
  let secretNames := {}
  for (let name in keys(inputs.secret_headers)) {
    secretNames[lower(name)] := true
  }

  let headers := {}
  for (let name, value in (inputs.headers ?? {})) {
    // A header name that a secret header also sets is dropped, because HTTP header names are
    // case insensitive and both values would otherwise go on the wire.
    if (not secretNames[lower(name)]) {
      headers[name] := value
    }
  }
  for (let name, value in inputs.secret_headers) {
    headers[name] := value
  }

  payload['headers'] := headers
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
            description: 'HTTP headers to send in the request.',
        },
        {
            key: 'secret_headers',
            type: 'dictionary',
            label: 'Secret headers',
            secret: true,
            required: false,
            description:
                'HTTP headers that hold a credential, such as an API token. These are encrypted, hidden after saving, and kept out of the logs. A secret header replaces the plaintext header of the same name.',
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
