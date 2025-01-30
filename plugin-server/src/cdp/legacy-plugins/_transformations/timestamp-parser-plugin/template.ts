import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-timestamp-parser-plugin',
    name: 'Timestamp Parser',
    description: 'Parse your event timestamps into useful date properties.',
    icon_url: 'https://raw.githubusercontent.com/posthog/timestamp-parser-plugin/main/logo.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [],
}
