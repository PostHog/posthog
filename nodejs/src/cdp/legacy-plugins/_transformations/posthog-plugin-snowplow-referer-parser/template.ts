import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const posthogPluginSnowplowRefererParser: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-posthog-plugin-snowplow-referer-parser',
        name: 'UTM Referrer',
        description: 'UTM referrer snowplow parser',
        icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
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
