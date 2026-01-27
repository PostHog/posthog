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
        code_language: 'javascript',
        code: 'return event',
        inputs_schema: [
            {
                templating: false,
                key: 'host',
                label: 'Host',
                type: 'string',
                description: 'E.g. posthog.yourcompany.com',
                required: true,
                secret: false,
            },
            {
                templating: false,
                key: 'project_api_key',
                label: 'Project API Key',
                type: 'string',
                description: 'Grab it from e.g. https://posthog.yourcompany.com/project/settings',
                required: true,
                secret: false,
            },
            {
                templating: false,
                key: 'replication',
                label: 'Replication',
                type: 'string',
                description: 'How many times should each event be sent',
                default: '1',
                required: false,
                secret: false,
            },
            {
                templating: false,
                key: 'events_to_ignore',
                label: 'Events to ignore',
                type: 'string',
                description: 'Comma-separated list of events to ignore, e.g. $pageleave, purchase',
                default: '',
                required: false,
                secret: false,
            },
            {
                templating: false,
                key: 'disable_geoip',
                label: 'Disable Geo IP?',
                type: 'choice',
                description:
                    "Add $disable_geoip so that the receiving PostHog instance doesn't try to resolve the IP address.",
                default: 'No',
                required: false,
                secret: false,
                choices: [
                    {
                        value: 'Yes',
                        label: 'Yes',
                    },
                    {
                        value: 'No',
                        label: 'No',
                    },
                ],
            },
        ],
    },
}
