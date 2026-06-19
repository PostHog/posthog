import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-update-person-properties',
    name: 'Update person properties',
    description: 'Updates properties of a PostHog person',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'Analytics'],
    code_language: 'hog',
    code: `
if (empty(inputs.distinct_id)) {
  throw Error('Distinct ID is required')
}

postHogCapture({
  'event': '$set',
  'distinct_id': inputs.distinct_id,
  'properties': {
    '$set': inputs.set_properties,
    '$set_once': inputs.set_once_properties
  }
})
`,
    inputs_schema: [
        {
            type: 'string',
            key: 'distinct_id',
            label: 'Distinct ID',
            required: true,
            secret: false,
            hidden: false,
            default: '{event.distinct_id}',
            description: 'The distinct ID associated with the Person.',
        },
        {
            type: 'dictionary',
            key: 'set_properties',
            label: 'Properties to set',
            required: false,
            default: {},
            secret: false,
            hidden: false,
            description: 'The properties to update on the person.',
        },
        {
            type: 'dictionary',
            key: 'set_once_properties',
            label: 'Properties to set once',
            required: false,
            default: {},
            secret: false,
            hidden: false,
            description: 'The properties to set if they do not already exist on the person.',
        },
    ],
}
