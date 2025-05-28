import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'beta',
    type: 'source_webhook',
    id: 'template-source-webhook',
    name: 'HTTP Incoming Webhook',
    description: 'Capture an event via a custom incoming webhook',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    hog: `
if(empty(inputs.event)) {
  throw Error('"event" cannot be empty')
}

if(empty(inputs.distinct_id)) {
  throw Error('"event" cannot be empty')
}

if(notEmpty(inputs.auth_header) and notEquals(inputs.auth_header, headers['authorization'])) {
  return {
    'httpResponse': {
      'status': 401,
      'body': 'Unauthorized',
    }
  }
}

postHogCapture({
    'event': inputs.event,
    'distinct_id': inputs.distinct_id,
    'properties': inputs.properties
})
`,
    inputs_schema: [
        {
            key: 'event',
            type: 'string',
            label: 'Event name',
            default: '{body.event}',
            secret: false,
            required: true,
        },
        {
            key: 'distinct_id',
            type: 'string',
            label: 'Distinct ID',
            description: 'The distinct ID this event should be associated with',
            default: '{body.distinct_id}',
            secret: false,
            required: true,
        },
        {
            key: 'properties',
            type: 'json',
            label: 'Event properties',
            description: 'A mapping of the incoming webhook body to the PostHog event properties',
            default: {},
            secret: false,
            required: false,
        },
        {
            key: 'auth_header',
            type: 'string',
            label: 'Secret auth token',
            description: 'If set, the incoming Authorization header must match this value exactly',
            secret: true,
            required: false,
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log payloads',
            description: 'Logs the incoming request for debugging',
            secret: false,
            required: false,
            default: false,
        },
    ],
}
