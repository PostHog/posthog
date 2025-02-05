import { LegacyDestinationPlugin } from '../../types'
import { onEvent } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const replicatorPlugin: LegacyDestinationPlugin = {
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-posthog-plugin-replicator',
        name: 'Replicator',
        description: 'Replicate PostHog event stream in another PostHog instance',
        icon_url: 'https://raw.githubusercontent.com/PostHog/posthog-plugin-replicator/master/logo.png',
        category: [],
        hog: 'return event',
        inputs_schema: [
            {
                key: 'host',
                description: 'E.g. posthog.yourcompany.com',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'project_api_key',
                description: 'Grab it from e.g. https://posthog.yourcompany.com/project/settings',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'replication',
                description: 'How many times should each event be sent',
                type: 'string',
                default: '1',
                required: true,
                secret: true,
            },
            {
                key: 'events_to_ignore',
                description: 'Comma-separated list of events to ignore, e.g. $pageleave, purchase',
                type: 'string',
                default: '',
                required: true,
                secret: true,
            },
            {
                key: 'disable_geoip',
                description:
                    "Add $disable_geoip so that the receiving PostHog instance doesn't try to resolve the IP address.",
                type: 'choice',
                default: 'No',
                required: true,
                secret: true,
                choices: [
                    { value: 'Yes', label: 'Yes' },
                    { value: 'No', label: 'No' },
                ],
            },
        ],
    },
}
