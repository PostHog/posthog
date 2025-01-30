import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-property-filter-plugin',
    name: 'Property Filter',
    description: 'This plugin will set all configured properties to null inside an ingested event.',
    icon_url: 'https://raw.githubusercontent.com/posthog/property-filter-plugin/dev/logo.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'properties',
            label: 'Properties to filter out',
            type: 'string',
            description: 'A comma-separated list of properties to filter out (e.g. $ip, $current_url)',
            default: '',
            required: true,
        },
    ],
}
