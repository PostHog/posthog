import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-posthog-filter-out-plugin',
    name: 'Filter Out Plugin',
    description: 'Filter out events where property values satisfy the given condition',
    icon_url: 'https://raw.githubusercontent.com/posthog/posthog-filter-out-plugin/main/logo.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'filters',
            label: 'Filters to apply',
            type: 'string',
            description: 'A JSON file containing an array of filters to apply. See the README for more information.',
            required: false,
        },
        {
            key: 'eventsToDrop',
            label: 'Events to filter out',
            type: 'string',
            description: 'A comma-separated list of event names to filter out (e.g. $pageview,$autocapture)',
            required: false,
        },
        {
            key: 'keepUndefinedProperties',
            label: 'Keep event if any of the filtered properties are undefined?',
            type: 'choice',
            choices: [
                { value: 'Yes', label: 'Yes' },
                { value: 'No', label: 'No' },
            ],
            default: 'No',
        },
    ],
}
