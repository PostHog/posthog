import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    free: false,
    status: 'deprecated',
    type: 'destination',
    id: 'plugin-hubspot-plugin',
    name: 'Hubspot',
    description: 'This plugin will send events to Hubspot.',
    icon_url: 'https://raw.githubusercontent.com/posthog/hubspot-plugin/main/logo.png',
    category: [],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'hubspotAccessToken',
            description: 'Can be acquired under Profile Preferences -> Integrations -> Private Apps',
            label: 'Hubspot Access Token',
            type: 'string',
            default: '',
            required: true,
            secret: true,
        },
        {
            key: 'triggeringEvents',
            description:
                'A comma-separated list of PostHog events you want to trigger Contact creation in HubSpot. By default, we recommend using the $identify event.',
            label: 'Triggering events',
            type: 'string',
            default: '$identify',
            required: true,
        },
        {
            key: 'additionalPropertyMappings',
            description:
                'A mapping of additional PostHog event or person properties to map to newly created Hubspot Contacts. Provide a comma-separated mapping of: personPropertylabel:hubSpotPropertyName',
            label: 'Additional PostHog to HubSpot property mappings',
            type: 'string',
            default: '',
            required: false,
        },
        {
            key: 'ignoredEmails',
            description: 'A comma-separated list of email domains to ignore and not create contacts for in Hubspot.',
            label: 'Email domains to skip',
            type: 'string',
            default: '',
            required: false,
        },
        {
            key: 'postHogUrl',
            description: 'Deprecated',
            label: 'PostHog Instance',
            type: 'string',
            default: 'https://app.posthog.com',
            required: false,
        },
        {
            key: 'posthogApiKey',
            description: 'Deprecated',
            label: 'PostHog API Key',
            type: 'string',
            default: '',
            secret: true,
            required: false,
        },
        {
            key: 'posthogProjectKey',
            description: 'Deprecated',
            label: 'Project API Key',
            type: 'string',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'syncMode',
            description: 'Deprecated',
            label: 'Debug Mode',
            type: 'choice',
            default: 'production',
            required: false,
            choices: [
                { value: 'production', label: 'production' },
                { value: 'debug', label: 'debug' },
            ],
        },
    ],
}
