import { HogFunctionTemplate } from '~/src/cdp/templates/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-ph-shotgun-processevent-app',
    name: 'Shotgun Process Event App',
    description: 'Process Shotgun events',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Transformation'],
    hog: `return event`,
    inputs_schema: [],
}
