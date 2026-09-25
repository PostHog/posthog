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

let res := fetch(inputs.url, payload);

// A listed status must reach the return below, so a workflow step can store it and branch on it.
// The match follows the executor's rules (exact codes, and the 4xx and 5xx wildcards). The executor
// also fails an unlisted status, but only this throw puts the response body in the step error.
if (res.status >= 400) {
  let nonFailure := false
  for (let code in inputs.non_failure_status_codes ?? []) {
    let entry := lower(toString(code))
    if (entry == toString(res.status) or (entry == '4xx' and res.status < 500) or (entry == '5xx' and res.status >= 500 and res.status < 600)) {
      nonFailure := true
    }
  }
  if (not nonFailure) {
    throw Error(f'Webhook failed with status {res.status}: {res.body}');
  }
}

if (inputs.debug) {
  print('Response', res.status, res.body);
}

return { 'status': res.status, 'body': res.body }
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
            key: 'signing_secret',
            type: 'string',
            label: 'Signing secret',
            secret: true,
            required: false,
            description: 'Signs each request following the [Standard Webhooks](https://www.standardwebhooks.com) spec.',
        },
        {
            key: 'non_failure_status_codes',
            type: 'non_failure_status_codes',
            label: 'Non-failure status codes',
            secret: false,
            required: false,
            description:
                'Status codes that should not fail this step. Accepts exact codes such as 404, or the wildcards 4xx and 5xx. Store the response in a workflow variable to branch on one of these codes instead of failing.',
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
