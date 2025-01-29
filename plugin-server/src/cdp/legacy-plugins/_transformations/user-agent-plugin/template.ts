import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-user-agent-plugin',
    name: 'User Agent Populator',
    description:
        "Enhances events with user agent details. User Agent plugin allows you to populate events with the $browser, $browser_version for PostHog Clients that don't  typically populate these properties",
    icon_url: '/static/transformations/user-agent.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'overrideUserAgentDetails',
            label: 'Can override existing browser related properties of event?',
            type: 'string',
            description:
                'If the ingested event already have $browser $browser_version properties in combination with $useragent the $browser, $browser_version properties will be re-populated with the value of $useragent',
            default: 'false',
            required: false,
        },
        {
            key: 'enableSegmentAnalyticsJs',
            label: 'Automatically read segment_userAgent property, automatically sent by Segment via analytics.js?',
            type: 'choice',
            description:
                "Segment's analytics.js library automatically sends a useragent property that Posthog sees as segment_userAgent. Enabling this causes this plugin to parse that property",
            choices: [
                { value: 'false', label: 'false' },
                { value: 'true', label: 'true' },
            ],
            default: 'false',
            required: false,
        },
        {
            key: 'debugMode',
            type: 'choice',
            description: 'Enable debug mode to log when the plugin is unable to extract values from the user agent',
            choices: [
                { value: 'false', label: 'false' },
                { value: 'true', label: 'true' },
            ],
            default: 'false',
            required: false,
        },
    ],
}
