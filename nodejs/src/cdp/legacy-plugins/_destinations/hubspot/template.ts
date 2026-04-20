import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const hubspotPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-hubspot-plugin',
        name: 'Hubspot',
        description: 'This plugin will send events to Hubspot.',
        icon_url: 'https://raw.githubusercontent.com/posthog/hubspot-plugin/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                templating: false,
                key: 'hubspotAccessToken',
                description: 'Can be acquired under Profile Preferences -> Integrations -> Private Apps',
                label: 'Hubspot Access Token',
                type: 'string',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'triggeringEvents',
                description:
                    'A comma-separated list of PostHog events you want to trigger Contact creation in HubSpot. By default, we recommend using the $identify event.',
                label: 'Triggering events',
                type: 'string',
                default: '$identify',
                required: true,
            },
            {
                templating: false,
                key: 'additionalPropertyMappings',
                description:
                    'A mapping of additional PostHog event or person properties to map to newly created Hubspot Contacts. Provide a comma-separated mapping of: personPropertylabel:hubSpotPropertyName',
                label: 'Additional PostHog to HubSpot property mappings',
                type: 'string',
                default: '',
                required: false,
            },
            {
                templating: false,
                key: 'ignoredEmails',
                description:
                    'A comma-separated list of email domains to ignore and not create contacts for in Hubspot.',
                label: 'Email domains to skip',
                type: 'string',
                default: '',
                required: false,
            },
        ],
    },
}
