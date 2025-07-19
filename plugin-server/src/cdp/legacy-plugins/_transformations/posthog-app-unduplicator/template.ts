import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from '.'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const posthogAppUnduplicator: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-posthog-app-unduplicator',
        name: 'PostHog App Unduplicator',
        description: 'Prevent duplicates in your data when ingesting.',
        icon_url: '/static/hedgehog/builder-hog-01.png',
        category: ['Custom'],
        code_language: 'javascript',
        hog: `return event`,
        inputs_schema: [
            {
                key: 'dedupMode',
                templating: false,
                label: 'Dedup Mode',
                type: 'choice',
                required: true,
                choices: [
                    { value: 'Event and Timestamp', label: 'Event and Timestamp' },
                    { value: 'All Properties', label: 'All Properties' },
                ],
            },
        ],
    },
}
