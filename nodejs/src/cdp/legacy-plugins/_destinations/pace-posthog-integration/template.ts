import { LegacyDestinationPlugin } from '../../types'
import { onEvent } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const pacePlugin: LegacyDestinationPlugin = {
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-pace-posthog-integration',
        name: 'Pace Integration',
        description:
            'Pace is a tool that equips sellers with relevant insights at the right time so they can spend time growing revenue. It allows them to convert, retain, and grow customers by prioritizing time and effort on the users who need it most.',
        icon_url: 'https://raw.githubusercontent.com/PostHog/pace-posthog-integration/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                templating: false,
                key: 'api_key',
                description: 'API key provided by Pace.',
                label: 'API Key',
                type: 'string',
                required: true,
                secret: true,
            },
        ],
    },
}
