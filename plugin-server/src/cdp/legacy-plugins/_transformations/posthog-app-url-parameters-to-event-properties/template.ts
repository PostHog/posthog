import { processEvent, setupPlugin } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const posthogAppUrlParametersToEventProperties: LegacyTransformationPlugin = {
    processEvent,
    setupPlugin: setupPlugin as any,
    template: {
        free: true,
        status: 'stable',
        type: 'transformation',
        id: 'plugin-posthog-app-url-parameters-to-event-properties',
        name: 'URL parameters to event properties',
        description: 'Converts URL query parameters to event properties',
        icon_url:
            'https://raw.githubusercontent.com/posthog/posthog-app-url-parameters-to-event-properties/main/logo.png',
        category: ['Transformation'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                key: 'parameters',
                templating: false,
                label: 'URL query parameters to convert',
                type: 'string',
                default: '',
                description:
                    'Comma separated list of URL query parameters to capture. Leaving this blank will capture nothing.',
            },
            {
                key: 'prefix',
                templating: false,
                label: 'Prefix',
                type: 'string',
                default: '',
                description:
                    "Add a prefix to the property name e.g. set it to 'prefix_' to get followerId -> prefix_followerId",
            },
            {
                key: 'suffix',
                templating: false,
                label: 'Suffix',
                type: 'string',
                default: '',
                description:
                    "Add a suffix to the property name e.g. set it to '_suffix' to get followerId -> followerId_suffix",
            },
            {
                key: 'ignoreCase',
                templating: false,
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
                templating: false,
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
                templating: false,
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
                templating: false,
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
    },
}
