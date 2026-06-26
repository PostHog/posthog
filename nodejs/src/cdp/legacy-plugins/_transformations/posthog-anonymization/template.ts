import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from './src/processEvent'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const posthogAnonymization: LegacyTransformationPlugin = {
    processEvent,
    template: {
        free: true,
        status: 'deprecated',
        type: 'transformation',
        id: 'plugin-posthog-anonymization',
        name: 'PostHog Anonymization',
        description: 'Anonymize your data.',
        icon_url: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png',
        category: ['Custom'],
        code_language: 'javascript',
        code: `return event`,
        inputs_schema: [
            {
                key: 'salt',
                templating: false,
                label: 'The salt.',
                type: 'string',
                required: true,
                secret: true,
            },
            {
                key: 'privateFields',
                templating: false,
                label: 'The names of fields to be anonymized divided by a comma.',
                type: 'string',
                default: 'distinct_id,name,userid',
                required: true,
            },
        ],
    },
}
