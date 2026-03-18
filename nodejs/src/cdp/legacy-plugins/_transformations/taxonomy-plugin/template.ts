import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const taxonomyPlugin: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'stable',
        type: 'transformation',
        id: 'plugin-taxonomy-plugin',
        name: 'Taxonomy',
        description: 'Standardize your event names into a single pattern.',
        icon_url: 'https://raw.githubusercontent.com/posthog/taxonomy-plugin/main/logo.png',
        category: ['Transformation'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                key: 'defaultNamingConvention',
                templating: false,
                label: 'Select your default naming pattern',
                type: 'choice',
                choices: [
                    { value: 'camelCase', label: 'camelCase' },
                    { value: 'PascalCase', label: 'PascalCase' },
                    { value: 'snake_case', label: 'snake_case' },
                    { value: 'kebab-case', label: 'kebab-case' },
                    { value: 'spaces in between', label: 'spaces in between' },
                ],
                default: 'camelCase',
                required: true,
            },
        ],
    },
}
