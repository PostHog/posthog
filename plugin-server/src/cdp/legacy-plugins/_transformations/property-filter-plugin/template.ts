import { processEvent, setupPlugin } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const propertyFilterPlugin: LegacyTransformationPlugin = {
    processEvent,
    setupPlugin,
    template: {
        free: true,
        status: 'stable',
        type: 'transformation',
        id: 'plugin-property-filter-plugin',
        name: 'Property Filter',
        description: 'This plugin will set all configured properties to null inside an ingested event.',
        icon_url: 'https://raw.githubusercontent.com/posthog/property-filter-plugin/dev/logo.png',
        category: ['Transformation'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                templating: false,
                key: 'properties',
                label: 'Properties to filter out',
                type: 'string',
                description: 'A comma-separated list of properties to filter out (e.g. $ip, $current_url)',
                default: '',
                required: true,
            },
        ],
    },
}
