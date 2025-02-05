import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const patternsPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-patterns-app',
        name: 'Patterns App',
        description: 'Send events data to Patterns App',
        icon_url: 'https://raw.githubusercontent.com/patterns-app/posthog-patterns-app/main/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'webhookUrl',
                label: 'Patterns Webhook URL',
                type: 'string',
                description: '',
                default: '',
                required: true,
                secret: false,
            },
            {
                key: 'allowedEventTypes',
                label: 'Event types to send to Patterns (comma-separated)',
                type: 'string',
                description: '',
                default: '',
                required: false,
                secret: false,
            },
        ],
    },
}
