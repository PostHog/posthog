import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from '.'

export const semverFlattenerPlugin: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'stable',
        type: 'transformation',
        id: 'plugin-semver-flattener-plugin',
        name: 'SemVer Flattener',
        description: 'This plugin will flatten semver versions in the specified properties.',
        icon_url: '/static/transformations/semver-flattener.png',
        category: ['Transformation'],
        code_language: 'javascript',
        hog: `return event`,
        inputs_schema: [
            {
                key: 'properties',
                templating: false,
                label: 'comma separated properties to explode version number from',
                type: 'string',
                description: 'my_version_number,app_version',
                default: '',
                required: true,
            },
        ],
    },
}
