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
        code_language: 'javascript',
        code: 'return event',
        inputs_schema: [
            {
                templating: false,
                key: 'webhookUrl',
                label: 'Patterns Webhook URL',
                type: 'string',
                required: true,
                secret: false,
            },
            {
                templating: false,
                key: 'allowedEventTypes',
                label: 'Event types to send to Patterns (comma-separated)',
                type: 'string',
                default: '',
                required: false,
                secret: false,
            },
        ],
    },
}
