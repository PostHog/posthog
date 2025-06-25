import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'source_webhook',
    id: 'template-source-webhook',
    name: 'HTTP Incoming Webhook',
    description: 'Capture an event via a custom incoming webhook',
    icon_url: '/static/services/webhook.svg',
    category: ['Custom'],
    hog: `

if(inputs.debug) {
  print('Incoming request:', request.body)
}

if(notEmpty(inputs.auth_header) and notEquals(inputs.auth_header, request.headers['authorization'])) {
  print('Incoming request denied due to bad authorization header')
  return {
    'httpResponse': {
      'status': 401,
      'body': 'Unauthorized',
    }
  }
}

if(empty(inputs.event)) {
  throw Error('"event" cannot be empty')
}

if(empty(inputs.distinct_id)) {
  throw Error('"distinct_id" cannot be empty')
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
            default: '{request.body.event}',
            secret: false,
            required: true,
        },
        {
            key: 'distinct_id',
            type: 'string',
            label: 'Distinct ID',
            description: 'The distinct ID this event should be associated with',
            default: '{request.body.distinct_id}',
            secret: false,
            required: true,
        },
        {
            key: 'properties',
            type: 'json',
            label: 'Event properties',
            description: 'A mapping of the incoming webhook body to the PostHog event properties',
            default: {
                $ip: '{request.ip}',
                $lib: 'posthog-webhook',
                $source_url: '{source.url}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'auth_header',
            type: 'string',
            label: 'Authorization header value',
            description:
                'If set, the incoming Authorization header must match this value exactly. e.g. "Bearer SECRET_TOKEN"',
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
