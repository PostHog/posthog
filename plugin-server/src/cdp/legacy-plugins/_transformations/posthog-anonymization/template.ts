import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-posthog-anonymization',
    name: 'PostHog Anonymization',
    description: 'Anonymize your data.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `return event`,
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
            label: 'The names of fields to be anonymized divided by a colon.',
            type: 'string',
            default: 'distinct_id,name,userid',
            required: true,
        },
    ],
}
