import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-t3-code',
    name: 'T3 Code',
    description:
        'Start a T3 Code agent run from a workflow. The run uses the prompt of a T3 Code scheduled task that runs on webhook.',
    icon_url: '/static/services/t3-code.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let failureReasons := {
  '401': 'T3 Code rejected the signature. Use the same signing secret here and on the T3 Code task.',
  '404': 'T3 Code has no task at this webhook URL. Copy the current URL from the task in T3 Code.',
  '409': 'The T3 Code task is turned off. Turn it on in T3 Code.',
  '410': 'T3 Code skipped the request because it was too old for the task.',
  '413': 'The request is larger than the 1 MB T3 Code accepts. Send less in the payload.',
  '429': 'T3 Code is limiting requests to this task. A task takes up to 60 requests a minute and 20 queued runs.'
}

let payload := inputs.payload ?? {}
if (not empty(inputs.instructions)) {
  payload.instructions := inputs.instructions
}
let body := jsonStringify(payload)

let headers := {
  'Content-Type': 'application/json',
  'x-posthog-delivery-id': generateUUIDv4()
}
if (not empty(inputs.signing_secret)) {
  headers['x-hub-signature-256'] := f'sha256={sha256HmacChainHex([inputs.signing_secret, body])}'
}

let res := fetch(inputs.webhook_url, {
  'method': 'POST',
  'headers': headers,
  'body': body
})

if (res.status >= 400) {
  let reason := failureReasons[toString(res.status)] ?? 'T3 Code could not start the task. Check the task in T3 Code.'
  throw Error(f'{reason} (status {res.status}: {res.body})')
}

return res.body
`,
    inputs_schema: [
        {
            key: 'webhook_url',
            type: 'string',
            label: 'Webhook URL',
            secret: true,
            required: true,
            templating: false,
            description:
                'The URL of a T3 Code scheduled task that runs on webhook. Copy it from the task in T3 Code under Settings > Scheduled tasks.',
        },
        {
            key: 'instructions',
            type: 'string',
            label: 'Instructions',
            secret: false,
            required: false,
            description:
                "What the agent should do. Sent as instructions in the request body: put {{body.instructions}} in the T3 Code task's prompt to pass it on.",
        },
        {
            key: 'payload',
            type: 'json',
            label: 'Data',
            secret: false,
            required: false,
            default: { event: '{event}', person: '{person}' },
            description:
                "Data sent in the request body. The T3 Code task's prompt reads it with placeholders such as {{body.event.event}} or {{body.person.properties.email}}.",
        },
        {
            key: 'signing_secret',
            type: 'string',
            label: 'Signing secret',
            secret: true,
            required: false,
            templating: false,
            description:
                'Signs each request with an HMAC-SHA256 signature in the x-hub-signature-256 header. Turn on Require signature on the T3 Code task with the same secret, hex encoding and the sha256= prefix.',
        },
    ],
}
