import { LegacyDestinationPlugin } from '../../types'
import { onEvent, setupPlugin } from './index'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const customerioPlugin: LegacyDestinationPlugin = {
    setupPlugin: setupPlugin as any,
    onEvent,
    template: {
        free: false,
        status: 'deprecated',
        type: 'destination',
        id: 'plugin-customerio-plugin',
        name: 'Customer.io',
        description: 'This plugin will send events to Customer.io.',
        icon_url: 'https://raw.githubusercontent.com/posthog/customerio-plugin/main/logo.png',
        category: [],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                templating: false,
                key: 'customerioSiteId',
                description: 'Provided during Customer.io setup.',
                label: 'Customer.io Site ID',
                type: 'string',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'customerioToken',
                description: 'Provided during Customer.io setup.',
                label: 'Customer.io API Key',
                type: 'string',
                required: true,
                secret: true,
            },
            {
                templating: false,
                key: 'host',
                label: 'Tracking Endpoint',
                description: 'Use the EU variant if your Customer.io account is based in the EU region.',
                type: 'choice',
                default: 'track.customer.io',
                choices: [
                    { value: 'track.customer.io', label: 'track.customer.io' },
                    { value: 'track-eu.customer.io', label: 'track-eu.customer.io' },
                ],
            },
            {
                templating: false,
                key: 'identifyByEmail',
                label: 'Identify by email',
                description:
                    'If enabled, the plugin will identify users by email instead of ID, whenever an email is available.',
                type: 'choice',
                default: 'No',
                choices: [
                    { value: 'Yes', label: 'Yes' },
                    { value: 'No', label: 'No' },
                ],
            },
            {
                templating: false,
                key: 'sendEventsFromAnonymousUsers',
                label: 'Filtering of Anonymous Users',
                type: 'choice',
                description:
                    "Customer.io pricing is based on the number of customers. This is an option to only send events from users that have been identified. Take into consideration that merging after identification won't work (as those previously anonymous events won't be there).",
                default: 'Send all events',
                choices: [
                    { value: 'Send all events', label: 'Send all events' },
                    {
                        value: 'Only send events from users that have been identified',
                        label: 'Only send events from users that have been identified',
                    },
                    {
                        value: 'Only send events from users with emails',
                        label: 'Only send events from users with emails',
                    },
                ],
            },
            {
                templating: false,
                key: 'eventsToSend',
                label: 'PostHog Event Allowlist',
                type: 'string',
                description: 'If this is set, only the specified events (comma-separated) will be sent to Customer.io.',
            },
            {
                key: 'legacy_plugin_config_id',
                label: 'Legacy plugin config ID',
                description: 'The ID of the legacy plugin config that this was migrated from. (DO NOT MODIFY THIS)',
                type: 'string',
                default: '',
                required: true,
            },
        ],
    },
}
