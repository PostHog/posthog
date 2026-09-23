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
  // Names only for headers and query: either can carry a credential, and nothing masks it on the
  // way to the logs. The names are what a GET request was missing, which is what this log is for.
  print('Incoming request:', request.method, 'query names:', keys(request.query), 'header names:', keys(request.headers), 'body:', request.body)
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

// A query string often carries the caller's credential (?api_key=...), and the properties
// mapping stores whatever arrives. Drop the keys that name one, one level into each mapped
// object, so a token ends up neither on the event nor in the person's property list.
let credentialNames := ['access_token', 'api_key', 'apikey', 'auth', 'authorization', 'key', 'password', 'secret', 'signature', 'token']
let properties := {}

for (let propertyKey, propertyValue in inputs.properties) {
  if (typeof(propertyValue) == 'object') {
    let kept := {}
    for (let key, value in propertyValue) {
      if (not (lower(key) in credentialNames)) {
        kept[key] := value
      }
    }
    properties[propertyKey] := kept
  } else {
    properties[propertyKey] := propertyValue
  }
}

postHogCapture({
  'event': inputs.event,
  'distinct_id': inputs.distinct_id,
  'properties': properties
})
`,
    inputs_schema: [
        {
            key: 'event',
            type: 'string',
            label: 'Event name',
            description:
                'The name of the event to capture. For a GET request such as a tracking pixel, read it from a query parameter with {request.query.event}.',
            default: '{request.body.event}',
            secret: false,
            required: true,
        },
        {
            key: 'distinct_id',
            type: 'string',
            label: 'Distinct ID',
            description:
                'The distinct ID this event should be associated with. For a GET request, read it from a query parameter with {request.query.distinct_id}.',
            default: '{request.body.distinct_id}',
            secret: false,
            required: true,
        },
        {
            key: 'properties',
            type: 'json',
            label: 'Event properties',
            description:
                'A mapping of the incoming request to the PostHog event properties. Use {request.body.x} for body values and {request.query.x} for query parameters.',
            default: {
                $ip: '{request.ip}',
                $lib: 'posthog-webhook',
                $source_url: '{source.url}',
                query_params: '{request.query}',
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
            description:
                'HTTP method to allow for the request. A tracking pixel or any other GET endpoint has to set this to GET, or the request is refused with a 405.',
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
