import { HogFunctionTemplate } from '../../../templates/types'

// NOTE: This is a deprecated plugin and should never be shown to new users
export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'plugin-stonly-clean-campaign-name',
    name: 'Clean Campaign Name',
    description: 'Clean campaign name',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `return event`,
    inputs_schema: [],
}
