import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from '.'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const posthogPluginSnowplowRefererParser: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-posthog-snowplow-referer-parser',
        name: 'UTM Referrer',
        description: 'UTM referrer snowplow parser',
        icon_url: '/static/hedgehog/builder-hog-01.png',
        category: ['Custom'],
        hog: `return event`,
        inputs_schema: [
            {
                templating: false,
                key: 'internal_domains',
                label: 'Internal domains (comma delimited)',
                type: 'string',
                description: 'Consider these domains as direct referrers. Example: `example.com,blog.example.com`',
                default: '',
                required: false,
            },
        ],
    },
}
