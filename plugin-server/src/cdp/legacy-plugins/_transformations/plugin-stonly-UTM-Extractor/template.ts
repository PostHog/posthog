import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from '.'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const pluginStonlyUtmExtractor: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-plugin-stonly-UTM-Extractor',
        name: 'UTM Extractor',
        description: 'UTM extractor',
        icon_url: '/static/hedgehog/builder-hog-01.png',
        category: ['Custom'],
        code_language: 'javascript',
        hog: `return event`,
        inputs_schema: [],
    },
}
