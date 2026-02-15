import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-capture',
    name: 'Capture a PostHog event',
    description: 'Capture a PostHog event to your account',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'Analytics'],
    code_language: 'hog',
    code: `
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
            secret: false,
            required: true,
            description: 'The name of the event to capture.',
        },
        {
            key: 'distinct_id',
            type: 'string',
            label: 'Distinct ID',
            secret: false,
            required: true,
            default: '{event.distinct_id}',
            description: 'The distinct ID to associate with the event.',
        },
        {
            key: 'properties',
            type: 'dictionary',
            label: 'Event properties',
            secret: false,
            required: false,
            description: 'The properties to include in the event.',
        },
    ],
}
