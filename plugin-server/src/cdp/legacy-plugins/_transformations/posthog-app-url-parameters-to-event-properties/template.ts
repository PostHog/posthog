import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-posthog-app-url-parameters-to-event-properties',
    name: 'URL parameters to event properties',
    description: 'Converts URL query parameters to event properties',
    icon_url: 'https://raw.githubusercontent.com/posthog/posthog-app-url-parameters-to-event-properties/main/logo.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'parameters',
            label: 'URL query parameters to convert',
            type: 'string',
            default: '',
            description:
                'Comma separated list of URL query parameters to capture. Leaving this blank will capture nothing.',
        },
        {
            key: 'prefix',
            label: 'Prefix',
            type: 'string',
            default: '',
            description:
                "Add a prefix to the property name e.g. set it to 'prefix_' to get followerId -> prefix_followerId",
        },
        {
            key: 'suffix',
            label: 'Suffix',
            type: 'string',
            default: '',
            description:
                "Add a suffix to the property name e.g. set it to '_suffix' to get followerId -> followerId_suffix",
        },
        {
            key: 'ignoreCase',
            label: 'Ignore the case of URL parameters',
            type: 'choice',
            choices: [
                { value: 'true', label: 'true' },
                { value: 'false', label: 'false' },
            ],
            default: 'false',
            description:
                'Ignores the case of parameters e.g. when set to true than followerId would match FollowerId, followerID, FoLlOwErId and similar',
        },
        {
            key: 'setAsUserProperties',
            label: 'Add to user properties',
            type: 'choice',
            choices: [
                { value: 'true', label: 'true' },
                { value: 'false', label: 'false' },
            ],
            default: 'false',
            description: 'Additionally adds the property to the user properties',
        },
        {
            key: 'setAsInitialUserProperties',
            label: 'Add to user initial properties',
            type: 'choice',
            choices: [
                { value: 'true', label: 'true' },
                { value: 'false', label: 'false' },
            ],
            default: 'false',
            description:
                "Additionally adds the property to the user initial properties. This will add a prefix of 'initial_' before the already fully composed property e.g. initial_prefix_followerId_suffix",
        },
        {
            key: 'alwaysJson',
            label: 'Always JSON stringify the property data',
            type: 'choice',
            choices: [
                { value: 'true', label: 'true' },
                { value: 'false', label: 'false' },
            ],
            default: 'false',
            description:
                'If set, always store the resulting data as a JSON array. (Otherwise, single parameters get stored as-is, and multi-value parameters get stored as a JSON array.)',
        },
    ],
}
