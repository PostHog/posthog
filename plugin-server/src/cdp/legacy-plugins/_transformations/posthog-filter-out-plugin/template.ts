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
            templating: false,
            label: 'Filters to apply',
            type: 'string',
            description: 'A JSON file containing an array of filters to apply. See the README for more information.',
            required: false,
        },
        {
            key: 'eventsToDrop',
            templating: false,
            label: 'Events to filter out',
            type: 'string',
            description: 'A comma-separated list of event names to filter out (e.g. $pageview,$autocapture)',
            required: false,
        },
        {
            key: 'keepUndefinedProperties',
            templating: false,
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
