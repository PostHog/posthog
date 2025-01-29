import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-semver-flattener-plugin',
    name: 'SemVer Flattener',
    description: 'This plugin will flatten semver versions in the specified properties.',
    icon_url: '/static/transformations/semver-flattener.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [
        {
            key: 'properties',
            label: 'comma separated properties to explode version number from',
            type: 'string',
            description: 'my_version_number,app_version',
            default: '',
            required: true,
        },
    ],
}
