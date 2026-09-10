import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const urlParserPlugin: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-url-parser-plugin',
        name: 'URL Params Parser (Beta)',
        description: 'Parse your event URLs into useful properties.',
        icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
        category: [],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
