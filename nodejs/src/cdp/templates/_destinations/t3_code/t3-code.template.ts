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
let payload := inputs.payload ?? {'event': event, 'person': person}
if (typeof(payload) != 'object') {
  payload := {'data': payload}
}
if (not empty(inputs.instructions)) {
  payload.instructions := inputs.instructions
}

let request := {
  'method': 'POST',
  'headers': {
    'Content-Type': 'application/json',
    'webhook-id': generateUUIDv4()
  },
  'body': payload
}
if (not empty(inputs.signing_secret)) {
  request.hmac_sha256 := {'secret_input': 'signing_secret'}
}

let res := fetch(inputs.webhook_url, request)

if (res.status >= 400) {
  throw Error(f'T3 Code did not start the task (status {res.status}: {res.body})')
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
                'The URL of a T3 Code scheduled task that runs on webhook. Copy it from the task in T3 Code under Settings > Scheduled tasks. Set the replay key of the task to {{headers.webhook-id}}, so a retried request does not start a second run.',
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
                "Data sent in the request body. The T3 Code task's prompt reads it with placeholders such as {{body.event.event}} or {{body.person.properties.email}}. Data that is not an object is sent as data.",
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
