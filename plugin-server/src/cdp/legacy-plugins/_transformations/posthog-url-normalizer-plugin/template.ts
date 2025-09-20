import { processEvent } from '.'

import { LegacyTransformationPlugin } from '../../types'

export const posthogUrlNormalizerPlugin: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'stable',
        type: 'transformation',
        id: 'plugin-posthog-url-normalizer-plugin',
        name: 'URL Normalizer',
        description:
            'Normalize the format of urls in your application allowing you to more easily compare them in insights.',
        icon_url: 'https://raw.githubusercontent.com/posthog/posthog-url-normalizer-plugin/main/logo.png',
        category: ['Transformation'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [],
    },
}
