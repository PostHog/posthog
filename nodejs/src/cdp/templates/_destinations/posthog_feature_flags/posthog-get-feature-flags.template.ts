import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-get-feature-flags',
    name: 'Get feature flags',
    description: 'Find feature flags in this project and save them to a workflow variable',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
return postHogGetFeatureFlags({
  'status': inputs.status,
  'search': inputs.search,
  'targeting_property': inputs.targeting_property,
  'targeting_value': inputs.targeting_value,
  'targeting_match': inputs.targeting_match,
  'created_more_than_days_ago': inputs.created_more_than_days_ago,
  'updated_more_than_days_ago': inputs.updated_more_than_days_ago,
  'limit': inputs.limit
})
`,
    inputs_schema: [
        {
            key: 'status',
            type: 'choice',
            label: 'Flag status',
            secret: false,
            required: true,
            default: 'enabled',
            choices: [
                { label: 'Enabled', value: 'enabled' },
                { label: 'Disabled', value: 'disabled' },
                { label: 'Any', value: 'any' },
            ],
        },
        {
            key: 'search',
            type: 'string',
            label: 'Key or name contains',
            secret: false,
            required: false,
            default: '',
            description: 'Only return flags whose key or name contains this text.',
        },
        {
            key: 'targeting_property',
            type: 'string',
            label: 'Release condition property',
            secret: false,
            required: false,
            default: '',
            description:
                'Only return flags with a release condition on this property, for example "email" or "project_id". Leave empty to skip this filter.',
        },
        {
            key: 'targeting_value',
            type: 'string',
            label: 'Release condition value',
            secret: false,
            required: false,
            default: '',
            description:
                'The value the release condition must equal, for example "2" or {person.properties.email}. Only conditions with the "equals" operator count.',
        },
        {
            key: 'targeting_match',
            type: 'choice',
            label: 'Release condition match',
            secret: false,
            required: false,
            default: 'includes',
            choices: [
                { label: 'Rolled out to this value', value: 'includes' },
                { label: 'Rolled out only to this value', value: 'only' },
            ],
            description:
                '"Only" skips flags that also roll out to other values or to everyone. This reads the release conditions. It does not evaluate the flag for a person.',
        },
        {
            key: 'created_more_than_days_ago',
            type: 'number',
            label: 'Created more than (days ago)',
            secret: false,
            required: false,
            description: 'For example, 7 returns flags created more than a week ago.',
        },
        {
            key: 'updated_more_than_days_ago',
            type: 'number',
            label: 'Last changed more than (days ago)',
            secret: false,
            required: false,
            description: 'For example, 7 returns flags that nobody changed in the last week.',
        },
        {
            key: 'limit',
            type: 'number',
            label: 'Maximum number of flags',
            secret: false,
            required: false,
            default: 25,
            description: 'Up to 100. Newest flags come first.',
        },
    ],
}
