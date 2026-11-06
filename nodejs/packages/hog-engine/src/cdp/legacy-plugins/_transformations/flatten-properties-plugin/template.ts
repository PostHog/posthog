import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

// NOTE: This is a deprecated plugin and should never be shown to new users

export const flattenPropertiesPlugin: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-flatten-properties-plugin',
        name: 'Flatten Properties',
        description:
            'This plugin will flatten all nested properties into a single property. You will not be billed for any events that this plugin drops.',
        icon_url: 'https://raw.githubusercontent.com/posthog/flatten-properties-plugin/main/logo.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                key: 'separator',
                templating: false,
                description:
                    "For example, to access the value of 'b' in a: { b: 1 } with separator '__', you can do 'a__b'",
                label: 'Select a separator format for accessing your nested properties',
                type: 'choice',
                choices: [
                    { value: '__', label: '__' },
                    { value: '.', label: '.' },
                    { value: '>', label: '>' },
                    { value: '/', label: '/' },
                ],
                default: '__',
                required: true,
            },
        ],
    },
}
