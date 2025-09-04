import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-group-identify',
    name: 'Update group properties',
    description: 'Updates properties of a PostHog group (requires Group Analytics addon)',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'Analytics'],
    code_language: 'hog',
    code: `
if (empty(inputs.group_key)) {
  throw Error('Group key is required')
}

if (empty(inputs.group_type)) {
  throw Error('Group type is required')
}

postHogCapture({
  'event': '$groupidentify',
  'distinct_id': f'{inputs.group_type}_{inputs.group_key}',
  'properties': {
    '$group_type': inputs.group_type,
    '$group_key': inputs.group_key,
    '$group_set': inputs.group_properties
  }
})
`,
    inputs_schema: [
        {
            type: 'string',
            key: 'group_type',
            label: 'Group type',
            required: true,
            secret: false,
            hidden: false,
            description: 'The key of the group (e.g organization, project)',
        },
        {
            type: 'string',
            key: 'group_key',
            label: 'Group ID',
            required: true,
            secret: false,
            hidden: false,
            description: "The ID of this group such as a database identifier (e.g. 1234-5678 or 'posthog.com')",
        },
        {
            type: 'dictionary',
            key: 'group_properties',
            label: 'Group properties',
            required: false,
            default: { id: '{inputs.group_key}' },
            secret: false,
            hidden: false,
            description: 'The properties to update on the group.',
        },
    ],
}
