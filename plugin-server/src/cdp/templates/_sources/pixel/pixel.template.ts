import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-webhook-pixel',
    name: 'Tracking pixel',
    description:
        'Capture an event using a 1x1 tracking pixel. Useful for embedding tracking where PostHog SDKs are not available such as emails.',
    icon_url: '/static/services/webhook.svg',
    category: ['Email', 'Tracking'],
    code_language: 'hog',
    code: `
if(inputs.debug) {
  print('Incoming request:', request.query)
}

if(not empty(inputs.distinct_id) and not empty(inputs.event)) {
  postHogCapture({
    'event': inputs.event,
    'distinct_id': inputs.distinct_id,
    'properties': inputs.properties
  })
}

return {
  'httpResponse': {
    'status': 200,
    'body': base64Decode('R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=='),
    'contentType': 'image/gif',
  }
}
`,
    inputs_schema: [
        {
            key: 'event',
            type: 'string',
            label: 'Event name',
            description:
                'The name of the event to capture. You can derive this from a query parameter, or hard code it unique to this tracking pixel.',
            default: '{request.query.ph_event}',
            secret: false,
            required: true,
        },
        {
            key: 'distinct_id',
            type: 'string',
            label: 'Distinct ID',
            description: 'The distinct ID this event should be associated with',
            default: '{request.query.ph_distinct_id}',
            secret: false,
            required: true,
        },
        {
            key: 'properties',
            type: 'json',
            label: 'Event properties',
            description: 'A mapping of the incoming webhook body to the PostHog event properties',
            default: {
                $lib: 'posthog-webhook',
                $source_url: '{source.url}',
                query_params: '{request.query}',
            },
            secret: false,
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
