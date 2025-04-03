import { HogFunctionTemplate, SUB_TEMPLATE_COMMON } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'beta',
    type: 'destination',
    id: 'template-webhook',
    name: 'HTTP Webhook',
    description: 'Sends a webhook templated by the incoming event data',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    hog: `
let headers := {}

for (let key, value in inputs.headers) {
    headers[key] := value
}
if (inputs.additional_headers) {
  for (let key, value in inputs.additional_headers) {
    headers[key] := value
  }
}

let payload := {
  'headers': headers,
  'body': inputs.body,
  'method': inputs.method
}

if (inputs.debug) {
  print('Request', inputs.url, payload)
}

let res := fetch(inputs.url, payload);

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
        },
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
            default: { 'Content-Type': 'application/json' },
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
    filters: { bytecode: ['_H', 1, 29] },
    mapping_templates: [
        {
            name: 'Webhook',
            include_by_default: true,
            filters: {
                events: [{ id: '$pageview', name: 'Pageview', type: 'events' }],
                bytecode: ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11, 3, 1, 4, 1],
            },
            inputs_schema: [
                {
                    key: 'body',
                    type: 'json',
                    label: 'JSON Body',
                    default: { event: '{event}', person: '{person}' },
                    secret: false,
                    required: false,
                },
                {
                    key: 'additional_headers',
                    type: 'dictionary',
                    label: 'Additional headers',
                    secret: false,
                    required: false,
                    default: {},
                },
            ],
        },
    ],
    sub_templates: [
        {
            ...SUB_TEMPLATE_COMMON['early-access-feature-enrollment'],
            id: 'early-access-feature-enrollment',
            name: 'HTTP Webhook on feature enrollment',
        },
        {
            ...SUB_TEMPLATE_COMMON['survey-response'],
            id: 'survey-response',
            name: 'HTTP Webhook on survey response',
        },
        {
            ...SUB_TEMPLATE_COMMON['activity-log'],
            id: 'activity-log',
            name: 'HTTP Webhook on team activity',
        },
        {
            ...SUB_TEMPLATE_COMMON['error-tracking-issue-created'],
            name: 'HTTP Webhook on issue created',
            description: 'Send a webhook when an issue is created.',
        },
        {
            ...SUB_TEMPLATE_COMMON['error-tracking-issue-reopened'],
            name: 'HTTP Webhook on issue reopened',
            description: 'Send a webhook when an issue is reopened.',
        },
    ],
}
