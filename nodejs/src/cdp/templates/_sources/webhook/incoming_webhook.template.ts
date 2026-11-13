import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-webhook',
    name: 'HTTP Incoming Webhook',
    description: 'Capture an event via a custom incoming webhook',
    icon_url: '/static/services/webhook.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if(inputs.debug) {
  print('Incoming request:', request.body)
}

if(request.method != inputs.method) {
  return {
    'httpResponse': {
      'status': 405,
      'body': 'Method not allowed'
    }
  }
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
  return {
    'httpResponse': {
      'status': 400,
      'body': {
        'error': '"event" could not be parsed correctly',
      }
    }
  }
}

if(empty(inputs.distinct_id)) {
  return {
    'httpResponse': {
      'status': 400,
      'body': {
        'error': '"distinct_id" could not be parsed correctly',
      }
    }
  }
}

if(notEmpty(inputs.uuid) and not match(inputs.uuid, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')) {
  return {
    'httpResponse': {
      'status': 400,
      'body': {
        'error': '"uuid" must be a UUID',
      }
    }
  }
}

postHogCapture({
  'event': inputs.event,
  'distinct_id': inputs.distinct_id,
  'uuid': inputs.uuid,
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
            key: 'uuid',
            type: 'string',
            label: 'Event UUID',
            description:
                'Sets the UUID of the event, such as an ID the sender repeats when it retries a delivery: {request.body.id}. The value must be a UUID, or the request fails with a 400 error. Leave empty to give each event a new UUID.',
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
            description: 'HTTP method to allow for the request.',
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
