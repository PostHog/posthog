import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-posthog-snowplow-referer-parser',
    name: 'UTM Referrer',
    description: '',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'internal_domains',
            templating: false,
            label: 'Internal domains (comma delimited)',
            type: 'string',
            description: 'Consider these domains as direct referrers. Example: `example.com,blog.example.com`',
            default: '',
            required: false,
        },
    ],
}
