import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-taxonomy-plugin',
    name: 'Taxonomy',
    description: 'Standardize your event names into a single pattern.',
    icon_url: 'https://raw.githubusercontent.com/posthog/taxonomy-plugin/main/logo.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'defaultNamingConvention',
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
}
