import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-posthog-url-normalizer-plugin',
    name: 'URL Normalizer',
    description:
        'Normalize the format of urls in your application allowing you to more easily compare them in insights.',
    icon_url: 'https://raw.githubusercontent.com/posthog/posthog-url-normalizer-plugin/main/logo.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [],
}
