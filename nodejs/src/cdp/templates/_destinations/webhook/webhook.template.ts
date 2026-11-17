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

if (not empty(inputs.secret_headers)) {
  payload['secret_headers_input'] := 'secret_headers'
}

if (inputs.continue_on_error) {
  payload['fail_on_error'] := false
  payload['max_tries'] := 1
}

if (not empty(inputs.timeout_ms)) {
  payload['timeout_ms'] := toInt(inputs.timeout_ms)
}

if (inputs.debug) {
  print('Request', inputs.url, payload)
}

let res := fetch(inputs.url, payload);

if (inputs.continue_on_error) {
  if (inputs.debug) {
    print('Response', res.status, res.body);
  }
  // Workflow variables are capped at 5 KB, so a long body is cut down to a string.
  let body := res.body
  if (typeof(body) != 'string' and length(jsonStringify(body)) > 1000) {
    body := jsonStringify(body)
  }
  if (typeof(body) == 'string') {
    body := substring(body, 1, 1000)
  }
  if (not empty(res.error)) {
    return {'status': 0, 'body': null, 'duration_ms': res.duration_ms, 'error': res.error}
  }
  return {'status': res.status, 'body': body, 'duration_ms': res.duration_ms, 'error': null}
}

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
                {
                    label: 'HEAD',
                    value: 'HEAD',
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
            key: 'signing_secret',
            type: 'string',
            label: 'Signing secret',
            secret: true,
            required: false,
            description: 'Signs each request following the [Standard Webhooks](https://www.standardwebhooks.com) spec.',
        },
        {
            key: 'continue_on_error',
            type: 'boolean',
            label: 'Continue on error responses',
            description:
                'Store the response and continue when the request fails or returns an error status, without retrying. Use this to check a URL and branch on the result. Response bodies longer than 1,000 characters are cut short.',
            secret: false,
            required: false,
            default: false,
        },
        {
            key: 'timeout_ms',
            type: 'number',
            label: 'Timeout (ms)',
            description: 'How long to wait for a response. The server limit applies when this is longer.',
            secret: false,
            required: false,
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
