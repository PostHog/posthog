import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const timestampParserPlugin: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'stable',
        type: 'transformation',
        id: 'plugin-timestamp-parser-plugin',
        name: 'Timestamp Parser',
        description: 'Parse your event timestamps into useful date properties.',
        icon_url: 'https://raw.githubusercontent.com/posthog/timestamp-parser-plugin/main/logo.png',
        category: ['Transformation'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
